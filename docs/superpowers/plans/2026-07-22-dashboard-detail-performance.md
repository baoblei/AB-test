# Dashboard Detail Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dashboard detail lists render hundreds of evaluation images smoothly by loading only cached thumbnails for the current page and fetching originals only after a user opens the image preview.

**Architecture:** Add a focused Pillow-backed thumbnail service and FastAPI route that resolve images through the existing safe storage functions and cache 256px WebP files. Keep detail JSON client-side, paginate filtered rows at 50 per page, lazily load only thumbnail URLs, debounce filename filtering, and release detail DOM/state on close. Existing preview payloads retain original URLs, but those URLs are assigned to image elements only inside `openPreview()` after a click.

**Tech Stack:** FastAPI, Starlette `FileResponse`, Pillow, vanilla JavaScript, Python `unittest`, Node.js probes.

## Global Constraints

- Detail list images use only 256px WebP thumbnail URLs.
- Original image URLs are fetched only after the user clicks a detail thumbnail and opens the existing high-resolution preview.
- Render at most 50 detail rows per page.
- Preserve current detail filtering, result presentation, evaluator filtering, and high-resolution preview behavior.
- Add no frontend dependency and do not modify original image files.
- Preserve user changes outside this worktree.

## File Structure

- Create `app_core/thumbnail_service.py`: safe source resolution, WebP generation, stable cache keys, atomic cache writes.
- Create `tests/test_thumbnail_service.py`: service and route behavior tests using real Pillow images.
- Create `tests/test_dashboard_detail_performance_ui.py`: source contracts and Node probes for pagination, URLs, debounce, stale responses, and cleanup.
- Modify `main.py`: register `/api/image-thumbnail` and return cached files with browser cache headers.
- Modify `templates/dashboard.html`: pagination UI/state, thumbnail URLs, lazy image attributes, debounce, stale-request guard, and cleanup.
- Modify `.gitignore`: ignore generated `.thumbnails/` cache files.

---

### Task 1: Cached Thumbnail Service and API

**Files:**
- Create: `app_core/thumbnail_service.py`
- Create: `tests/test_thumbnail_service.py`
- Modify: `main.py:1-270`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `app_core.storage.get_result_image_path()`, `app_core.storage.get_ref_image_path()`, `AppError`, `NotFoundError`, Pillow `Image` and `ImageOps`.
- Produces: `get_image_thumbnail(kind, task_type, scene, filename, model=None, cache_root=THUMBNAIL_CACHE_DIR, max_size=256) -> str` and `GET /api/image-thumbnail`.

- [ ] **Step 1: Write failing service tests**

Create `tests/test_thumbnail_service.py` with real 2048×1024 and 900×1800 source images. Patch the storage resolvers and assert the service returns a WebP whose longest edge is 256, preserves aspect ratio, reuses the same cache file without changing its mtime, and returns a different cache path after the source file mtime/content changes. Include these exact behavior assertions:

```python
thumbnail = get_image_thumbnail(
    "result", "T2I", "scene", "image.png", model="model-a",
    cache_root=cache_root,
)
with Image.open(thumbnail) as image:
    self.assertEqual(image.format, "WEBP")
    self.assertEqual(image.size, (256, 128))
self.assertEqual(
    get_image_thumbnail("result", "T2I", "scene", "image.png", model="model-a", cache_root=cache_root),
    thumbnail,
)
```

Add separate tests asserting missing result models, unsupported `kind`, missing sources, and unsafe storage components raise `AppError` or `NotFoundError` rather than reading arbitrary paths.

- [ ] **Step 2: Run service tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_thumbnail_service -v
```

Expected: import failure because `app_core.thumbnail_service` does not exist.

- [ ] **Step 3: Implement the minimal thumbnail service**

Implement these public boundaries and cache rules:

```python
THUMBNAIL_CACHE_DIR = Path(".thumbnails")

def get_image_thumbnail(
    kind: str,
    task_type: str,
    scene: str,
    filename: str,
    model: Optional[str] = None,
    cache_root: Path = THUMBNAIL_CACHE_DIR,
    max_size: int = 256,
) -> str:
    source = _resolve_source(kind, task_type, scene, filename, model)
    source_stat = os.stat(source)
    identity = f"{kind}\0{task_type}\0{model or ''}\0{scene}\0{filename}\0{source_stat.st_size}\0{source_stat.st_mtime_ns}"
    destination = Path(cache_root) / f"{hashlib.sha256(identity.encode()).hexdigest()}.webp"
    if destination.is_file():
        return os.fspath(destination)
    _write_thumbnail(source, destination, max_size)
    return os.fspath(destination)
```

`_resolve_source()` must accept only `result` and `ref`, require `model` for results, and use existing safe storage resolvers. `_write_thumbnail()` must create the cache directory, use `ImageOps.exif_transpose()`, call `thumbnail((max_size, max_size), Image.Resampling.LANCZOS)`, save WebP to a temporary file in the cache directory, then `os.replace()` it into place. It must remove leftover temporary files in `finally` and never modify the source.

- [ ] **Step 4: Run service tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_thumbnail_service -v
```

Expected: all service tests pass.

- [ ] **Step 5: Add failing API route tests**

In `tests/test_thumbnail_service.py`, use `TestClient(main.app)` and patch `main.get_image_thumbnail`. Assert:

```python
response = client.get("/api/image-thumbnail", params={
    "kind": "result", "task_type": "T2I", "model": "model-a",
    "scene": "scene", "filename": "image.png",
})
self.assertEqual(response.status_code, 200)
self.assertEqual(response.headers["content-type"], "image/webp")
self.assertEqual(response.headers["cache-control"], "public, max-age=3600")
```

Also assert a reference request passes `model=None` and a missing result model returns HTTP 400.

- [ ] **Step 6: Run API tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_thumbnail_service -v
```

Expected: route test receives 404 because `/api/image-thumbnail` is not registered.

- [ ] **Step 7: Register the route and ignore the cache**

Import `get_image_thumbnail` and add:

```python
@app.get("/api/image-thumbnail")
def image_thumbnail(kind: str, task_type: str, scene: str, filename: str, model: Optional[str] = None):
    path = get_image_thumbnail(kind, task_type, scene, filename, model)
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=3600"},
    )
```

Add `.thumbnails/` to `.gitignore`.

- [ ] **Step 8: Run backend tests and commit**

Run:

```bash
python3 -m unittest tests.test_thumbnail_service tests.test_export_archive tests.test_task_0_review_fixes -v
```

Expected: all tests pass. Then commit only Task 1 files:

```bash
git add .gitignore app_core/thumbnail_service.py main.py tests/test_thumbnail_service.py
git commit -m "feat: serve cached dashboard thumbnails"
```

---

### Task 2: Detail Pagination, Thumbnail-Only List Loading, and Cleanup

**Files:**
- Create: `tests/test_dashboard_detail_performance_ui.py`
- Modify: `templates/dashboard.html:610-650`
- Modify: `templates/dashboard.html:780-810`
- Modify: `templates/dashboard.html:1479-1575`
- Modify: `templates/dashboard.html:1753-1805`
- Modify: `templates/dashboard.html:2135-2137`

**Interfaces:**
- Consumes: existing `imageUrl()`, `buildPreviewPayload()`, `openPreview()`, `createNode()`, and detail filters.
- Produces: `DETAIL_PAGE_SIZE`, `paginateDetailRows(rows, page, pageSize)`, `detailThumbnailUrl(kind, model, scene, filename)`, `scheduleDetailRender()`, `resetDetailPage()`, `changeDetailPage(delta)`, `cleanupDetailModal()`, and `#detail-pagination`.

- [ ] **Step 1: Write failing pure-function and markup tests**

Create `tests/test_dashboard_detail_performance_ui.py`. Extract JavaScript functions from the template like existing dashboard UI tests and use Node to assert:

```javascript
paginateDetailRows(Array.from({ length: 121 }, (_, index) => index), 1, 50)
// page=1, totalPages=3, items length=50, first item=0

paginateDetailRows(Array.from({ length: 121 }, (_, index) => index), 99, 50)
// page=3, totalPages=3, items length=21, first item=100
```

Assert the template includes `id="detail-pagination"`, previous/next controls, `const DETAIL_PAGE_SIZE = 50`, `scheduleDetailRender()`, and a 200ms timer. Assert `detailThumbnailUrl()` produces `/api/image-thumbnail` with encoded query parameters for both result and ref requests.

- [ ] **Step 2: Run UI tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_detail_performance_ui -v
```

Expected: failure because pagination markup and helper functions do not exist.

- [ ] **Step 3: Add pagination markup and state helpers**

Add a pagination container below the detail table and state fields:

```javascript
const DETAIL_PAGE_SIZE = 50;
// state fields: detailPage, detailRenderTimer, detailRequestId

function paginateDetailRows(rows, page, pageSize = DETAIL_PAGE_SIZE) {
    const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
    const currentPage = Math.max(1, Math.min(totalPages, Number(page) || 1));
    const start = (currentPage - 1) * pageSize;
    return { items: rows.slice(start, start + pageSize), page: currentPage, totalPages };
}
```

`renderDetailTable()` must compute the full filtered count, paginate it, assign the clamped page to state, render only `pagination.items`, and update disabled states and `第 N / M 页` text. `resetDetailPage()` sets page 1 before rendering; `changeDetailPage(delta)` adjusts state and renders.

- [ ] **Step 4: Run pagination tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_dashboard_detail_performance_ui -v
```

Expected: pagination and URL helper tests pass.

- [ ] **Step 5: Add failing thumbnail-only image tests**

Add contracts proving the detail table sets each list image to `detailThumbnailUrl(...)`, plus:

```javascript
image.loading = "lazy";
image.decoding = "async";
image.fetchPriority = "low";
image.width = 76;
image.height = 76;
```

Extract `renderDetailTable()` and assert its source does not assign `imageUrl(...)` or `row.ref_img` to `image.src`. Separately assert `buildPreviewPayload()` still creates original `imageUrl()` strings and `openPreview()` is the function that assigns those original strings to preview image elements. This is the regression contract that originals are downloaded only after a click opens preview.

- [ ] **Step 6: Run thumbnail-only tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_detail_performance_ui -v
```

Expected: failure because the table still assigns original URLs to `image.src`.

- [ ] **Step 7: Switch table images to thumbnail URLs**

Add:

```javascript
function detailThumbnailUrl(kind, model, scene, filename) {
    const params = new URLSearchParams({ kind, task_type: state.taskType, scene, filename });
    if (kind === "result") params.set("model", model);
    return `/api/image-thumbnail?${params.toString()}`;
}
```

For TI2I references, include a thumbnail only when `row.ref_img` exists, but set its `src` from `detailThumbnailUrl("ref", "", scene, row.filename)`. For both result images, use `detailThumbnailUrl("result", model, scene, row.filename)`. Keep the existing click handler and original `preview` payload unchanged.

- [ ] **Step 8: Add failing debounce, stale-response, and cleanup tests**

Assert filename input calls `scheduleDetailRender()`, the timer is 200ms, changing result/evaluator filters resets to page 1, and `openDetailModal()` checks a request id after awaiting JSON. Use a Node DOM stub to call `cleanupDetailModal()` and assert:

```json
{
  "rows": 0,
  "workers": 0,
  "currentDetail": null,
  "page": 1,
  "bodyChildren": 0,
  "paginationChildren": 0
}
```

Also assert `closeModal("detail-modal")` calls cleanup and increments `detailRequestId`, so a response arriving after close is ignored.

- [ ] **Step 9: Run lifecycle tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_detail_performance_ui -v
```

Expected: failure because debounce, request invalidation, and cleanup do not exist.

- [ ] **Step 10: Implement debounce, stale guard, and cleanup**

Implement `scheduleDetailRender()` using one 200ms timeout, reset the page before the delayed render, and clear the timer in cleanup. In `openDetailModal()`, increment and capture `detailRequestId`, then ignore the response unless the id still matches and the modal remains open. `cleanupDetailModal()` must clear list/pagination nodes and all detail state. `closeModal()` must call it only for `detail-modal` before hiding the modal.

- [ ] **Step 11: Run frontend tests and commit**

Run:

```bash
python3 -m unittest tests.test_dashboard_detail_performance_ui tests.test_dashboard_export_ui tests.test_evaluation_preview_ui -v
```

Expected: all tests pass. Then commit:

```bash
git add templates/dashboard.html tests/test_dashboard_detail_performance_ui.py
git commit -m "perf: paginate dashboard detail thumbnails"
```

---

### Task 3: End-to-End Regression Verification

**Files:**
- Read: `docs/superpowers/specs/2026-07-22-dashboard-detail-performance-design.md`
- Read: all changed production and test files

**Interfaces:**
- Consumes: Tasks 1 and 2 behavior.
- Produces: verified implementation with no extra source changes.

- [ ] **Step 1: Run focused behavior tests**

Run:

```bash
python3 -m unittest tests.test_thumbnail_service tests.test_dashboard_detail_performance_ui -v
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass with zero failures.

- [ ] **Step 3: Check syntax, whitespace, and changed scope**

Run:

```bash
python3 -m py_compile main.py app_core/thumbnail_service.py tests/test_thumbnail_service.py tests/test_dashboard_detail_performance_ui.py
git diff --check HEAD~2..HEAD
git status --short
git diff --stat main...HEAD
```

Expected: compilation and diff checks exit 0; status contains no unintended generated files; changed files match the plan.

- [ ] **Step 4: Review completion criteria**

Confirm directly in source and tests that current-page rows are capped at 50, detail list image `src` values are all thumbnail endpoints, original URLs appear only in the click-opened preview path, search is debounced, stale requests are ignored, and detail close releases DOM/state.
