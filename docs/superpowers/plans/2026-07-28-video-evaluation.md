# T2V and TI2V Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production-ready T2V/TI2V upload, configurable-dimension evaluation, synchronized video playback, first-frame dashboard previews, exports, and twelve mock videos without changing existing T2I/TI2I behavior.

**Architecture:** Extend the existing capability-driven FastAPI services with two video task configs and a canonical per-user evaluation-scope table. Keep image routes and URLs stable, isolate FFmpeg frame extraction in a small media module, and share a browser-side video playback group between the evaluation and dashboard templates. Store fixed requested video scores in nullable columns while preserving the current four-way result semantics.

**Tech Stack:** Python 3.9, FastAPI, SQLite, Pydantic, Pillow, imageio-ffmpeg, openpyxl, vanilla HTML/CSS/JavaScript, Node-based frontend contract tests, Python unittest.

## Global Constraints

- Preserve the existing T2I/TI2I setup controls, `full/overall` modes, desktop layout, image preview behavior, dashboard layout, and export behavior.
- T2V dimensions, in order: 整体、文本一致性、运动合理性、动态度、物理规律与常识、画面细节与美感.
- TI2V appends 图像一致性 after the T2V dimensions.
- Overall is optional for video evaluation; at least one dimension must be selected.
- An equal selected set resumes, a strict superset confirms then deletes old scope results and restarts, and a subset or incomparable set is rejected without mutation.
- T2V/TI2V result ZIPs accept `.mp4` and `.webm`; TI2V requires reference images and T2V does not.
- Dashboard detail and bad-case lists load first-frame WebP thumbnails only; original video loads only inside evaluation or HD preview.
- The sidebar Sync button controls A/B play, pause, and seek as well as visual transforms; without Sync, videos are independent.
- Frame comparison and magnifier actions require videos to be paused.
- Never stage or commit the untracked local `database.db`.
- Every production behavior change follows a witnessed RED → GREEN cycle.

## File Responsibility Map

- `app_core/config.py`: task capabilities, video dimensions, labels, and accepted extensions.
- `app_core/dimensions.py`: canonical video dimension selection and set-transition classification.
- `app_core/database.py`: idempotent score columns and `evaluation_scopes` schema.
- `app_core/schemas.py`: video vote fields and selected-dimension payload.
- `app_core/task_service.py`: video session replacement/resume rules, stale-tab protection, and selected-score writes.
- `app_core/video_media.py`: managed FFmpeg execution and first-frame WebP extraction.
- `app_core/storage.py`: task-aware ZIP parsing/extraction, staged video upload, and reference requirements.
- `app_core/thumbnail_service.py`: image-versus-video thumbnail generation and cache warming.
- `app_core/dashboard_service.py`: non-null dimension denominators and dynamic detail score payloads.
- `app_core/dataset_download_service.py`: capability-based TXT/reference ZIP routing.
- `app_core/export_service.py`: selected-mode filtering, video dimensions, first-frame metadata, and original-media archives.
- `app_core/user_service.py`: video scores and selected dimensions in personal history payloads.
- `main.py`: capability payloads and selected-dimension session arguments.
- `static/video_media.js`: shared custom controls, synchronization, drift correction, frame capture, and cleanup.
- `templates/index.html`: video-only dimension setup, media panes, paused-frame preview adapters, and vote payloads.
- `templates/dashboard.html`: video-only two-row cards, first-frame lists, on-demand HD videos, adaptive upload/export copy.
- `scripts/generate_mock_video_dataset.py`: deterministic mock reference images and MP4 fixtures.
- `README.md`: T2V/TI2V usage, data layout, formats, and sample models.

---

### Task 1: Task capabilities, dimension canonicalization, and schema

**Files:**
- Create: `app_core/dimensions.py`
- Create: `tests/test_video_config_schema.py`
- Modify: `app_core/config.py:7-87`
- Modify: `app_core/database.py:91-184`
- Modify: `app_core/schemas.py:22-38`
- Modify: `main.py:95-118`

**Interfaces:**
- Produces: `VIDEO_EXTENSIONS`, `VIDEO_SCORE_DIMENSIONS`, `is_video_task(task_type)`, `canonical_selected_dimensions(task_type, values) -> list[str]`, and `dimension_transition(previous, current) -> str`.
- Produces: SQLite `evaluation_scopes` and nullable video score columns.
- Produces: `/api/task_config` fields `media_type`, `result_extensions`, and `upload_has_ref`.

- [ ] **Step 1: Write failing capability and schema tests**

Create `tests/test_video_config_schema.py` with focused assertions:

```python
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_core.config import TASK_CONFIGS
from app_core.database import init_db
from app_core.dimensions import canonical_selected_dimensions, dimension_transition


class VideoConfigTests(unittest.TestCase):
    def test_video_task_capabilities_and_dimension_order(self):
        self.assertEqual(TASK_CONFIGS["T2V"]["media_type"], "video")
        self.assertEqual(TASK_CONFIGS["TI2V"]["result_extensions"], (".mp4", ".webm"))
        self.assertFalse(TASK_CONFIGS["T2V"]["upload_has_ref"])
        self.assertTrue(TASK_CONFIGS["TI2V"]["upload_has_ref"])
        self.assertEqual(
            TASK_CONFIGS["T2V"]["dashboard_dims"],
            ["overall", "text_consistency", "motion_reasonableness", "dynamism", "physical_plausibility", "visual_quality"],
        )
        self.assertEqual(TASK_CONFIGS["TI2V"]["dashboard_dims"][-1], "image_consistency")
        self.assertEqual(TASK_CONFIGS["T2I"]["media_type"], "image")

    def test_dimension_selection_is_validated_and_canonicalized(self):
        self.assertEqual(
            canonical_selected_dimensions("T2V", ["dynamism", "overall"]),
            ["overall", "dynamism"],
        )
        for values in ([], ["overall", "overall"], ["fidelity"]):
            with self.subTest(values=values), self.assertRaises(Exception):
                canonical_selected_dimensions("T2V", values)

    def test_dimension_transition_uses_set_inclusion(self):
        self.assertEqual(dimension_transition(["overall"], ["overall"]), "equal")
        self.assertEqual(dimension_transition(["overall"], ["overall", "dynamism"]), "superset")
        self.assertEqual(dimension_transition(["overall", "dynamism"], ["overall"]), "subset")
        self.assertEqual(dimension_transition(["overall"], ["dynamism"]), "incomparable")


class VideoSchemaTests(unittest.TestCase):
    def test_init_db_adds_video_scores_and_scope_table_idempotently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "test.db"
            with patch("app_core.database.DB_PATH", str(database)):
                init_db()
                init_db()
            conn = sqlite3.connect(database)
            result_columns = {row[1] for row in conn.execute("PRAGMA table_info(results_log)")}
            scope_columns = {row[1] for row in conn.execute("PRAGMA table_info(evaluation_scopes)")}
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(evaluation_scopes)")}
            conn.close()
        self.assertTrue({
            "text_consistency", "motion_reasonableness", "dynamism",
            "physical_plausibility", "visual_quality", "image_consistency",
            "selected_dimensions",
        }.issubset(result_columns))
        self.assertTrue({"user_id", "task_type", "v_a", "v_b", "scene", "selected_dimensions"}.issubset(scope_columns))
        self.assertIn("idx_evaluation_scopes_unique", indexes)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused tests and witness RED**

Run: `python3 -m unittest tests.test_video_config_schema -v`

Expected: import failure for `app_core.dimensions` or missing `T2V` config/schema assertions.

- [ ] **Step 3: Implement capabilities, canonicalization, and schema**

In `app_core/config.py`, add `VIDEO_EXTENSIONS = (".mp4", ".webm")`, media capabilities to both existing image configs, T2V/TI2V configs, and these labels:

```python
DIM_LABELS.update({
    "text_consistency": "文本一致性",
    "motion_reasonableness": "运动合理性",
    "dynamism": "动态度",
    "physical_plausibility": "物理规律与常识",
    "visual_quality": "画面细节与美感",
    "image_consistency": "图像一致性",
})

VIDEO_SCORE_DIMENSIONS = (
    "text_consistency",
    "motion_reasonableness",
    "dynamism",
    "physical_plausibility",
    "visual_quality",
    "image_consistency",
)


def is_video_task(task_type: str) -> bool:
    return get_task_config(task_type)["media_type"] == "video"
```

Create `app_core/dimensions.py`:

```python
from collections.abc import Iterable
from typing import Optional

from .config import get_task_config, is_video_task
from .errors import AppError


def canonical_selected_dimensions(task_type: str, values: Optional[Iterable[str]]) -> list[str]:
    if not is_video_task(task_type):
        raise AppError("图片任务不支持自定义评测维度")
    received = list(values or [])
    if not received:
        raise AppError("请至少选择一个评测维度")
    if len(received) != len(set(received)):
        raise AppError("评测维度不能重复")
    configured = list(get_task_config(task_type)["dashboard_dims"])
    invalid = [dimension for dimension in received if dimension not in configured]
    if invalid:
        raise AppError("包含无效评测维度")
    selected = set(received)
    return [dimension for dimension in configured if dimension in selected]


def dimension_transition(previous: Iterable[str], current: Iterable[str]) -> str:
    old = set(previous)
    new = set(current)
    if old == new:
        return "equal"
    if old < new:
        return "superset"
    if new < old:
        return "subset"
    return "incomparable"
```

In `app_core/database.py`, add the six nullable score columns plus `selected_dimensions TEXT DEFAULT '[]'` to table creation and `ensure_column`, then create the scope table and unique index:

```python
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS evaluation_scopes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        task_type TEXT NOT NULL,
        v_a TEXT NOT NULL,
        v_b TEXT NOT NULL,
        scene TEXT NOT NULL,
        selected_dimensions TEXT NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )
    """
)
cursor.execute(
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluation_scopes_unique
    ON evaluation_scopes(user_id, task_type, v_a, v_b, scene)
    """
)
```

Add the six optional fields and `selected_dimensions: List[str] = Field(default_factory=list)` to `VoteSubmit`. Extend the task-config response with the three capability fields without removing old keys.

- [ ] **Step 4: Run focused and compatibility tests**

Run: `python3 -m unittest tests.test_video_config_schema tests.test_task_0_review_fixes tests.test_task_mode_integrity -v`

Expected: all tests pass and database initialization remains idempotent.

- [ ] **Step 5: Commit Task 1**

```bash
git add app_core/config.py app_core/dimensions.py app_core/database.py app_core/schemas.py main.py tests/test_video_config_schema.py
git commit -m "feat: add video task capabilities and schema"
```

---

### Task 2: Selected-dimension session lifecycle and vote writes

**Files:**
- Create: `tests/test_video_task_service.py`
- Modify: `app_core/task_service.py:15-688`
- Modify: `main.py:172-223`
- Test: `tests/test_task_mode_integrity.py`
- Test: `tests/test_task_completion_atomicity.py`

**Interfaces:**
- Consumes: `canonical_selected_dimensions` and `dimension_transition` from Task 1.
- Produces: `start_eval_session(..., selected_dimensions=None, overwrite_dimensions=False)` and task payload `selected_dimensions`.
- Produces: `eval_mode=selected` vote/skip rows with exact selected scores and all unselected scores `NULL`.

- [ ] **Step 1: Write failing lifecycle and vote tests**

Create temporary-database tests that start a T2V scope, insert a completed result, and assert each transition. Use this exact public behavior:

```python
first = start_eval_session(
    "T2V", "alice", "test_A_default", "test_B_default", "motion",
    "selected", 1, selected_dimensions=["overall"],
)
self.assertEqual(first["status"], "ok")

same = start_eval_session(
    "T2V", "alice", "test_A_default", "test_B_default", "motion",
    "selected", 1, selected_dimensions=["overall"],
)
self.assertEqual(same["dimension_transition"], "equal")

confirm = start_eval_session(
    "T2V", "alice", "test_A_default", "test_B_default", "motion",
    "selected", 1, selected_dimensions=["overall", "dynamism"],
)
self.assertEqual(confirm["status"], "requires_confirmation")

restarted = start_eval_session(
    "T2V", "alice", "test_A_default", "test_B_default", "motion",
    "selected", 1, selected_dimensions=["dynamism", "overall"],
    overwrite_dimensions=True,
)
self.assertEqual(restarted["dimension_transition"], "superset")
self.assertEqual(self.scalar("SELECT COUNT(*) FROM results_log"), 0)
self.assertEqual(self.scalar("SELECT COUNT(*) FROM pair_tasks WHERE status='pending'"), 3)
```

Add separate tests asserting subset and incomparable selections raise `AppError` without deleting results. Add a vote test using `SimpleNamespace` with `selected_dimensions=["dynamism"]`, `dynamism="left"`, and values in unselected fields; assert only `dynamism` is stored and all other score columns, including `overall`, are `NULL`. Add a stale-tab test that changes the scope and asserts the old working task raises `ConflictError`.

- [ ] **Step 2: Run and witness RED**

Run: `python3 -m unittest tests.test_video_task_service -v`

Expected: `start_eval_session` rejects `selected` or does not accept `selected_dimensions`.

- [ ] **Step 3: Implement video session state and dynamic scoring**

Allow `selected` in `normalize_eval_mode`, but reject it for image task session starts. Add scope helpers with canonical JSON:

```python
def _load_video_scope(cursor, task_type, v_a, v_b, scene, user_id):
    row = cursor.execute(
        """
        SELECT selected_dimensions FROM evaluation_scopes
        WHERE user_id=? AND task_type=? AND v_a=? AND v_b=? AND scene=?
        """,
        (user_id, task_type, v_a, v_b, scene),
    ).fetchone()
    return json.loads(row[0]) if row else None


def _write_video_scope(cursor, task_type, v_a, v_b, scene, user_id, dimensions):
    timestamp = now_beijing_iso()
    payload = json.dumps(dimensions, ensure_ascii=False)
    cursor.execute(
        """
        INSERT INTO evaluation_scopes
        (user_id, task_type, v_a, v_b, scene, selected_dimensions, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, task_type, v_a, v_b, scene)
        DO UPDATE SET selected_dimensions=excluded.selected_dimensions, updated_at=excluded.updated_at
        """,
        (user_id, task_type, v_a, v_b, scene, payload, timestamp, timestamp),
    )
```

Route video starts through `_start_video_eval_session`. For strict supersets, return confirmation before mutation; on confirmed overwrite, delete all result rows for the exact user scope, update/reset pair tasks, and write the new scope in one `BEGIN IMMEDIATE` transaction. For rejected transitions, raise before any write.

When retrieving a selected-mode task, query the scope and include it in the returned payload. In `submit_vote`, obtain the scope after the transaction begins, canonicalize `vote.selected_dimensions`, compare it to the stored list, and resolve only selected keys:

```python
all_video_dimensions = get_task_config(task_type)["dashboard_dims"]
dim_values = {dimension: None for dimension in all_video_dimensions}
for dimension in selected_dimensions:
    value = getattr(vote, dimension, None)
    if not value:
        raise AppError("请完成所有已选评分维度")
    dim_values[dimension] = resolve_vote_choice(value, vote.v_left, vote.v_right)
```

Expand the explicit `INSERT INTO results_log` statement with all six video columns and `selected_dimensions`. Selected-mode skips store the current scope JSON and all score columns as `NULL`. Keep the current image-mode branch and mode-exclusivity checks intact.

In `main.py`, accept `dimensions: Optional[str]` and `overwrite_dimensions: bool` on the start route, parse the JSON list with a clear `AppError` on invalid JSON, and pass both optional arguments after the existing parameters so direct image-service callers remain compatible.

- [ ] **Step 4: Run session, concurrency, and image-mode tests**

Run: `python3 -m unittest tests.test_video_task_service tests.test_task_mode_integrity tests.test_task_completion_atomicity tests.test_four_way_task_service tests.test_business_time_writes -v`

Expected: all tests pass, including the existing full/overall concurrency tests.

- [ ] **Step 5: Commit Task 2**

```bash
git add app_core/task_service.py main.py tests/test_video_task_service.py tests/test_task_mode_integrity.py tests/test_task_completion_atomicity.py
git commit -m "feat: enforce video evaluation dimension scopes"
```

---

### Task 3: Video ZIP staging and first-frame thumbnail pipeline

**Files:**
- Create: `app_core/video_media.py`
- Create: `tests/test_video_storage.py`
- Create: `tests/test_video_thumbnail_service.py`
- Modify: `app_core/storage.py:93-114, 375-413, 544-718`
- Modify: `app_core/thumbnail_service.py:1-93`
- Modify: `app_core/dataset_download_service.py:171-183`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `extract_first_frame_webp(source, max_size=256) -> bytes`.
- Produces: task-aware `zip_media_infos`, staged `upload_result_zip`, and cache-warmed video thumbnails.
- Preserves: `/api/image-thumbnail` and existing storage resolver names.

- [ ] **Step 1: Write failing storage and thumbnail tests**

Add tests that construct ZIP bytes in memory and patch prompt IDs. Required assertions:

```python
with patch("app_core.storage.get_prompt_ids", return_value=["clip_01"]):
    validation = validate_result_zip("T2V", "motion", mp4_zip_bytes)
self.assertEqual(validation["media_count"], 1)

with patch("app_core.storage.get_prompt_ids", return_value=["clip_01"]):
    with self.assertRaisesRegex(AppError, "视频"):
        validate_result_zip("T2V", "motion", png_zip_bytes)

with patch("app_core.storage.get_prompt_ids", return_value=["image_01"]):
    image_validation = validate_result_zip("T2I", "portrait", png_zip_bytes)
self.assertEqual(image_validation["image_count"], 1)
```

Test `extract_first_frame_webp` by patching `imageio_ffmpeg.get_ffmpeg_exe` and `subprocess.run` to return a small valid PNG on stdout, then open the result with Pillow and assert WebP dimensions. Test non-zero return code and empty stdout both raise `AppError("视频无法提取首帧")`.

Test `upload_result_zip` with a temporary result root and patched decoder. Assert all staged videos are decoded before an existing target scene is replaced, failure preserves the old directory, success returns `media_count`, and cache warming is called after replacement.

- [ ] **Step 2: Run and witness RED**

Run: `python3 -m unittest tests.test_video_storage tests.test_video_thumbnail_service -v`

Expected: missing `app_core.video_media`, `.mp4` ignored by result ZIP parsing, and image-only thumbnail failure.

- [ ] **Step 3: Implement managed FFmpeg extraction and staged uploads**

Add `imageio-ffmpeg>=0.5,<0.6` to `requirements.txt`. Create `app_core/video_media.py`:

```python
import io
import subprocess

import imageio_ffmpeg
from PIL import Image, UnidentifiedImageError

from .errors import AppError


def extract_first_frame_webp(source: str, max_size: int = 256) -> bytes:
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", source,
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=30, check=False)
        if completed.returncode != 0 or not completed.stdout:
            raise AppError("视频无法提取首帧")
        with Image.open(io.BytesIO(completed.stdout)) as opened:
            frame = opened.convert("RGB")
            frame.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            frame.save(output, format="WEBP", quality=82, method=4)
            return output.getvalue()
    except (OSError, subprocess.SubprocessError, UnidentifiedImageError) as exc:
        raise AppError("视频无法提取首帧") from exc
```

Refactor ZIP discovery to accept an explicit extension tuple and media label. Keep `zip_image_infos` as the reference-image wrapper so existing tests/callers remain valid. `list_scene_files` must use `get_task_config(task_type)["result_extensions"]`.

For video uploads, extract into a temporary sibling directory, decode every final renamed file, and only then replace the target. If the target exists, move it to a unique backup, move staging into place, warm cache entries, and remove the backup; on replacement failure restore the backup. Image uploads continue through the current path.

In `thumbnail_service`, retain `_write_thumbnail` for images and add atomic `_write_video_thumbnail` using `extract_first_frame_webp`. Select it only when `kind == "result"` and the task's `media_type` is `video`. Expose `warm_result_thumbnail(task_type, model, scene, filename)` as a thin call to `get_image_thumbnail`.

Change dataset upload and download reference branching from literal `TI2I/T2I` comparisons to `upload_has_ref`. This yields TXT-only behavior for T2V and optional reference ZIP behavior for TI2V.

- [ ] **Step 4: Run focused plus existing upload/download/thumbnail tests**

Run: `python3 -m unittest tests.test_video_storage tests.test_video_thumbnail_service tests.test_thumbnail_service tests.test_model_catalog tests.test_dataset_download tests.test_dashboard_dataset_download_ui -v`

Expected: all pass; legacy image ZIP names and thumbnail bytes remain unchanged.

- [ ] **Step 5: Commit Task 3**

```bash
git add requirements.txt app_core/video_media.py app_core/storage.py app_core/thumbnail_service.py app_core/dataset_download_service.py tests/test_video_storage.py tests/test_video_thumbnail_service.py
git commit -m "feat: add staged video uploads and first-frame thumbnails"
```

---

### Task 4: Shared video controls and evaluation-page UI

**Files:**
- Create: `static/video_media.js`
- Create: `tests/test_video_evaluation_ui.py`
- Modify: `main.py:35-47`
- Modify: `templates/index.html:1-2578`
- Test: `tests/test_evaluation_preview_ui.py`
- Test: `tests/test_four_way_evaluation_ui.py`
- Test: `tests/test_frontend_time_contract.py`

**Interfaces:**
- Consumes: task config `media_type`, `dashboard_dims`, task payload `selected_dimensions`, and first-frame thumbnail URLs.
- Produces: global `VideoPlaybackGroup`, custom pane controls, Sync-linked time operations, and paused-frame capture.

- [ ] **Step 1: Write failing DOM-free controller and template contract tests**

In `tests/test_video_evaluation_ui.py`, load `static/video_media.js` and execute it in Node with fake media elements. Verify the public API:

```javascript
const group = new VideoPlaybackGroup({ sync: true });
group.add("left", leftVideo);
group.add("right", rightVideo);
await group.play("left");
group.seek("left", 1.75);
group.pause("right");
```

Assert both videos receive play, `currentTime === 1.75`, and pause while Sync is on. Toggle `group.setSync(false)`, repeat operations, and assert only the source video changes. Assert `group.canUseFrameTools()` is false while any affected video plays and true after pause. Assert `group.destroy()` pauses videos, removes sources, calls `load()`, and clears listeners.

Add template assertions that:

- `id="video-dimension-selector"` exists and is shown only when `state.config.media_type === "video"`.
- `getActiveEvalDims()` returns selected video chips but preserves the current image branch exactly.
- `prepareEvalSession` sends JSON dimensions and `overwrite_dimensions` only for video.
- `renderMediaCard` creates `<video>` for A/B video panes but preserves `<img>` for TI2V reference.
- The vote payload includes all six video keys and `selected_dimensions`.
- Video control CSS hides `.video-controls` outside hover/focus.

- [ ] **Step 2: Run and witness RED**

Run: `python3 -m unittest tests.test_video_evaluation_ui -v`

Expected: missing shared JavaScript file, selector, media card, and video vote fields.

- [ ] **Step 3: Implement the shared controller and video-only evaluation branches**

Mount `StaticFiles(directory="static")` at `/static` and include `/static/video_media.js` before the inline evaluation script.

Implement `VideoPlaybackGroup` as an IIFE-exported class with `add`, `remove`, `setSync`, `play`, `pause`, `seek`, `canUseFrameTools`, `captureFrame`, and `destroy`. Use a private propagation flag while mirroring events; during `timeupdate`, correct peers only when absolute drift exceeds `0.15` seconds.

Add video-only setup chips generated from `state.config.dashboard_dims`. Maintain `state.selectedDimensions` in config order, default to all, and reject an empty set before the session request. Preserve the current `overallOnly` state and checkbox for image tasks.

Use these mode helpers:

```javascript
function isVideoTask() {
    return state.config?.media_type === "video";
}

function getEvalMode() {
    return isVideoTask() ? "selected" : (state.overallOnly ? "overall" : "full");
}

function getActiveEvalDims() {
    if (isVideoTask()) {
        const selected = new Set(state.selectedDimensions);
        return state.config.dashboard_dims.filter(dimension => selected.has(dimension.key));
    }
    return state.overallOnly
        ? [{ key: "overall", label: "整体" }]
        : [{ key: "overall", label: "整体" }, ...state.config.eval_dims];
}
```

Replace image-only A/B rendering with `renderMediaCard` that keeps reference panes as images and creates video panes with `poster=resultThumbnailUrl(model, scene, filename)`, `preload="metadata"`, `playsInline=true`, `muted=true`, and native controls disabled. Add `resultThumbnailUrl` beside the existing result URL helper and build its query with `URLSearchParams`. Create the translucent play/time/range control bar inside each video card. Use pointer/focus classes for visibility and call the shared group for play/pause/seek.

Extend the existing preview adapter so video panes measure `videoWidth/videoHeight` and receive the same transforms. Gate magnifier and hold-compare on `canUseFrameTools`; capture the paused source frame to a canvas data URL for overlay/magnifier sources. Leave non-frame toolbar actions available.

Start evaluation timing after both candidate videos emit `loadeddata` or already have `readyState >= 2`. On task transition, destroy the prior playback group before replacing DOM. Extend submit payload with canonical selected dimensions and all video score keys.

- [ ] **Step 4: Run evaluation UI and image regression tests**

Run: `python3 -m unittest tests.test_video_evaluation_ui tests.test_evaluation_preview_ui tests.test_four_way_evaluation_ui tests.test_evaluation_shortcuts_ui tests.test_frontend_time_contract -v`

Run: `node --check static/video_media.js`

Expected: all tests pass and JavaScript syntax check exits 0.

- [ ] **Step 5: Commit Task 4**

```bash
git add main.py static/video_media.js templates/index.html tests/test_video_evaluation_ui.py tests/test_evaluation_preview_ui.py tests/test_four_way_evaluation_ui.py tests/test_frontend_time_contract.py
git commit -m "feat: add configurable video evaluation UI"
```

---

### Task 5: Video dashboard aggregation, layout, and HD preview

**Files:**
- Create: `tests/test_video_dashboard.py`
- Create: `tests/test_video_dashboard_ui.py`
- Modify: `app_core/dashboard_service.py:29-255`
- Modify: `templates/dashboard.html:1-3303`
- Test: `tests/test_dashboard_detail_performance_ui.py`
- Test: `tests/test_dashboard_image_preview_ui.py`
- Test: `tests/test_four_way_dashboard.py`

**Interfaces:**
- Produces: non-null dimension denominators and configured-order `active_dims` at overview, pair, scene, and worker levels.
- Produces: first-frame-only detail tables and on-demand video HD panes using `VideoPlaybackGroup`.

- [ ] **Step 1: Write failing dashboard service and UI tests**

Add service tests with selected-mode dictionary rows:

```python
rows = [
    {"eval_mode": "selected", "overall": None, "dynamism": "A"},
    {"eval_mode": "selected", "overall": "B", "dynamism": None},
    {"eval_mode": "selected", "overall": "tie_good", "dynamism": "tie_bad"},
]
self.assertEqual(dimension_stats(rows, "overall", "A", "B")["total"], 2)
self.assertEqual(dimension_stats(rows, "dynamism", "A", "B")["total"], 2)
```

Patch `fetch_result_rows` with T2V rows and assert overview active dimensions contain only configured keys with a non-null result and preserve config order.

Add HTML/Node contract tests asserting:

- `summary-grid video-dimensions` is attached only when `state.config.media_type === "video"`.
- Video CSS uses `grid-template-columns: repeat(4, minmax(0, 1fr))` while the original `.summary-grid` rule remains unchanged.
- `renderDetailTable` always appends `<img>` thumbnails and contains no `createNode("video")`.
- `renderDashboardPreviewPane` creates a video only when `pane.mediaType === "video"`.
- `closeImagePreview` destroys the playback group and removes media sources.
- TI2V reference panes use `mediaType: "image"` between A/B video panes.
- Dataset upload enables the reference ZIP for TI2V but not T2V, and result upload sets `.mp4,.webm` accept/copy only for video tasks.

- [ ] **Step 2: Run and witness RED**

Run: `python3 -m unittest tests.test_video_dashboard tests.test_video_dashboard_ui -v`

Expected: selected rows are incorrectly counted by mode, and dashboard has no video grid/media branches.

- [ ] **Step 3: Implement non-null aggregation and on-demand video preview**

Change dimension scoping to score presence:

```python
def rows_for_dimension(rows: list, dim: str) -> list:
    return [row for row in rows if row[dim] is not None]


def active_dimensions(rows: list, configured: list[str]) -> list[str]:
    return [dimension for dimension in configured if any(row[dimension] is not None for row in rows)]
```

Include configured-order active dimensions in overview/pair/scene/worker payloads. Add all video score fields and a `scores` mapping to detail rows while retaining existing fixed keys.

In `dashboard.html`, use `state.overview.dims` and each pair's active dimensions instead of assuming every configured dimension has data. Add a video-only four-column grid modifier at render time. Keep image task class strings unchanged.

Leave detail and bad-case list creation as `<img>` and continue pointing at `/api/image-thumbnail`. Add `mediaType` to HD preview pane descriptors. Include the shared script and instantiate a playback group only after a video preview opens. Reuse the custom controls and Sync state from Task 4; use image adapters for references and video adapters for candidates. On close, pause, clear `src`, call `load`, destroy the group, clear compare layers, and replace preview children.

Update `syncDatasetUploadMode` and `handleResultTaskTypeChange` to use the fetched task capabilities. TI2V requires/enables reference ZIP exactly as TI2I does; T2V disables it exactly as T2I does. Set the result file input `accept` and upload status nouns to images for image tasks and `.mp4,.webm`/videos for video tasks.

- [ ] **Step 4: Run dashboard service and UI regressions**

Run: `python3 -m unittest tests.test_video_dashboard tests.test_video_dashboard_ui tests.test_four_way_dashboard tests.test_dashboard_detail_performance_ui tests.test_dashboard_image_preview_ui tests.test_dashboard_model_hierarchy_ui -v`

Expected: all tests pass; detail renderer remains thumbnail-only.

- [ ] **Step 5: Commit Task 5**

```bash
git add app_core/dashboard_service.py templates/dashboard.html tests/test_video_dashboard.py tests/test_video_dashboard_ui.py tests/test_dashboard_detail_performance_ui.py tests/test_dashboard_image_preview_ui.py
git commit -m "feat: add video dashboard previews and dimensions"
```

---

### Task 6: Video-aware export and personal history

**Files:**
- Create: `tests/test_video_export.py`
- Modify: `app_core/export_service.py:30-717`
- Modify: `app_core/user_service.py:86-115`
- Modify: `templates/dashboard.html:1030-1075, 2940-3199`
- Test: `tests/test_export_filtering.py`
- Test: `tests/test_export_workbook.py`
- Test: `tests/test_export_archive.py`

**Interfaces:**
- Consumes: task media/reference capabilities, video score fields, result file resolver, and first-frame thumbnail service.
- Produces: selected-mode workbook rows and original MP4/WebM ZIP members; preserves `include_images` as the API field name.

- [ ] **Step 1: Write failing export and history tests**

Create T2V/TI2V dictionary rows containing `eval_mode="selected"`, selected JSON, and mixed null score values. Assert:

```python
request = ExportRequest(
    task_type="T2V", v1="A", v2="B",
    dimensions=["overall", "dynamism"],
    eval_modes=["selected"], include_images=True,
)
self.assertEqual([row["id"] for row in filter_rows(rows, request, "overall")], [2])
self.assertEqual([row["id"] for row in filter_rows(rows, request, "dynamism")], [1])
```

Assert the workbook contains “整体” and “动态度”, uses “视频信息” and “视频路径” headers, and does not fabricate a value for a null dimension. Build an archive with temporary `.mp4` sources and assert original extensions and bytes survive under media entries; for TI2V assert a reference image is included. Patch user DB rows and assert history exposes `selected_dimensions` plus all video score keys.

- [ ] **Step 2: Run and witness RED**

Run: `python3 -m unittest tests.test_video_export -v`

Expected: `selected` is rejected, video dimensions are invalid, or archive/header assertions fail.

- [ ] **Step 3: Implement video export semantics and adaptive copy**

Add `selected` to valid modes. For video tasks, allow `request.dimensions` from `dashboard_dims`, including Overall; require `eval_modes == ["selected"]`. For images, preserve current validation.

Make `filter_rows` require only `row[dimension] is not None` for selected mode. Add a helper so selected result dimensions are:

```python
def _selected_result_dimensions(dimensions, request, task_type):
    if get_task_config(task_type)["media_type"] == "video":
        requested = set(request.dimensions)
        return [dimension for dimension in get_task_config(task_type)["dashboard_dims"] if dimension in requested]
    result = ["overall"] if "overall" in request.eval_modes else []
    result.extend(dimensions)
    return result
```

Use `upload_has_ref` instead of a `TI2I` literal for manifest reference entries. For video tasks, adapt workbook group/header copy to “视频信息”, “视频路径”, and “视频状态”; archive original sources unchanged. Add cached poster paths under `posters/<scene>/<model>/<stem>.webp` when media export is enabled, and expose them as “首帧路径” columns. Keep image archive members and headers byte-for-byte compatible with existing tests.

In dashboard export UI, set selected mode and include Overall among dimension chips for video tasks, hide the image-only mode choices, and relabel “导出图片” to “导出视频”; retain `include_images` in the JSON request. Update preview count copy from “去重图片” to “去重视频” only for video.

Extend `get_my_history` SELECT and response mappings with `selected_dimensions` and six video fields. The existing profile summary may continue showing Overall or `-` when Overall was not selected.

- [ ] **Step 4: Run export, profile, and permission regressions**

Run: `python3 -m unittest tests.test_video_export tests.test_export_filtering tests.test_export_workbook tests.test_export_archive tests.test_dashboard_export_ui tests.test_four_way_profile_ui tests.test_role_permissions -v`

Expected: all tests pass; image archive paths and existing workbook headers remain unchanged.

- [ ] **Step 5: Commit Task 6**

```bash
git add app_core/export_service.py app_core/user_service.py templates/dashboard.html tests/test_video_export.py tests/test_export_filtering.py tests/test_export_workbook.py tests/test_export_archive.py tests/test_dashboard_export_ui.py
git commit -m "feat: export video evaluations and media"
```

---

### Task 7: Deterministic mock T2V/TI2V data and documentation

**Files:**
- Create: `scripts/generate_mock_video_dataset.py`
- Create: `tests/test_mock_video_dataset.py`
- Create: `prompt/T2V/motion_basics.txt`
- Create: `prompt/TI2V/image_animation.txt`
- Create: `ref_images/TI2V/image_animation/animation_01.png`
- Create: `ref_images/TI2V/image_animation/animation_02.png`
- Create: `ref_images/TI2V/image_animation/animation_03.png`
- Create: `results/T2V/test_Nova_default/motion_basics/motion_01.mp4`
- Create: `results/T2V/test_Nova_default/motion_basics/motion_02.mp4`
- Create: `results/T2V/test_Nova_default/motion_basics/motion_03.mp4`
- Create: `results/T2V/test_Orbit_default/motion_basics/motion_01.mp4`
- Create: `results/T2V/test_Orbit_default/motion_basics/motion_02.mp4`
- Create: `results/T2V/test_Orbit_default/motion_basics/motion_03.mp4`
- Create: `results/TI2V/test_Frame_default/image_animation/animation_01.mp4`
- Create: `results/TI2V/test_Frame_default/image_animation/animation_02.mp4`
- Create: `results/TI2V/test_Frame_default/image_animation/animation_03.mp4`
- Create: `results/TI2V/test_Flow_default/image_animation/animation_01.mp4`
- Create: `results/TI2V/test_Flow_default/image_animation/animation_02.mp4`
- Create: `results/TI2V/test_Flow_default/image_animation/animation_03.mp4`
- Modify: `README.md`

**Interfaces:**
- Produces: reproducible 640×360, 12 fps, four-second, H.264/yuv420p silent MP4 fixtures.
- Produces: two discoverable video model pairs and six prompt/media identities.

- [ ] **Step 1: Write failing fixture structure and decode tests**

Create `tests/test_mock_video_dataset.py`:

```python
import unittest
from pathlib import Path

from app_core.storage import parse_prompt_file_bytes
from app_core.video_media import extract_first_frame_webp


class MockVideoDatasetTests(unittest.TestCase):
    def test_expected_models_prompts_references_and_videos_exist(self):
        t2v_ids = parse_prompt_file_bytes(Path("prompt/T2V/motion_basics.txt").read_bytes())["ids"]
        ti2v_ids = parse_prompt_file_bytes(Path("prompt/TI2V/image_animation.txt").read_bytes())["ids"]
        self.assertEqual(t2v_ids, ["motion_01", "motion_02", "motion_03"])
        self.assertEqual(ti2v_ids, ["animation_01", "animation_02", "animation_03"])
        video_paths = list(Path("results/T2V").glob("test_*_default/motion_basics/*.mp4"))
        video_paths += list(Path("results/TI2V").glob("test_*_default/image_animation/*.mp4"))
        refs = list(Path("ref_images/TI2V/image_animation").glob("*.png"))
        self.assertEqual(len(video_paths), 12)
        self.assertEqual(len(refs), 3)
        self.assertTrue(all(path.stat().st_size > 0 for path in video_paths))

    def test_every_mock_video_has_a_decodable_first_frame(self):
        videos = list(Path("results/T2V").rglob("*.mp4")) + list(Path("results/TI2V").rglob("*.mp4"))
        self.assertEqual(len(videos), 12)
        for video in videos:
            with self.subTest(video=video):
                self.assertGreater(len(extract_first_frame_webp(str(video))), 100)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and witness RED**

Run: `python3 -m unittest tests.test_mock_video_dataset -v`

Expected: missing prompt/video/reference fixture paths.

- [ ] **Step 3: Implement the deterministic generator and generate assets**

The generator uses Pillow for reference/frame drawing and `imageio_ffmpeg.write_frames` for encoding. Define immutable fixture metadata:

```python
T2V_MODELS = ("test_Nova_default", "test_Orbit_default")
TI2V_MODELS = ("test_Frame_default", "test_Flow_default")
SIZE = (640, 360)
FPS = 12
FRAME_COUNT = 48
```

For each frame, draw a background, prompt identifier, model label, and moving geometric subject. Nova/Frame use smooth linear or circular motion; Orbit/Flow use visibly different eased, bouncing, or faster paths. TI2V reference PNGs use the exact first-frame composition before animation.

Encode with:

```python
writer = imageio_ffmpeg.write_frames(
    str(output_path), SIZE, fps=FPS, codec="libx264", pix_fmt_in="rgb24",
    output_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an"],
)
writer.send(None)
try:
    for frame in frames:
        writer.send(frame.convert("RGB").tobytes())
finally:
    writer.close()
```

Run: `python3 scripts/generate_mock_video_dataset.py`

Expected: the script reports 12 generated videos and 3 reference images.

Update `README.md` with four task types, MP4/WebM upload rules, video dimension labels, selected-set replacement rules, folder examples, mock model names, first-frame dashboard behavior, and synchronized playback controls.

- [ ] **Step 4: Verify fixtures and discovery**

Run: `python3 -m unittest tests.test_mock_video_dataset tests.test_model_catalog tests.test_preview_prompt_services -v`

Run: `python3 -c 'from app_core.storage import get_versions_for_type; print(get_versions_for_type("T2V")); print(get_versions_for_type("TI2V"))'`

Expected: fixture tests pass and output contains both T2V and both TI2V model directories.

- [ ] **Step 5: Commit Task 7**

```bash
git add scripts/generate_mock_video_dataset.py tests/test_mock_video_dataset.py README.md prompt/T2V prompt/TI2V ref_images/TI2V results/T2V results/TI2V
git commit -m "feat: add mock video evaluation datasets"
```

---

### Task 8: Full regression, runtime walkthrough, and requirement audit

**Files:**
- Modify only files required to repair failures directly caused by Tasks 1–7.
- Update: `.planning/video-evaluation/task_plan.md`
- Update: `.planning/video-evaluation/progress.md`

**Interfaces:**
- Consumes all prior task outputs.
- Produces fresh automated, syntax, data, and browser verification evidence.

- [ ] **Step 1: Run the complete automated suite**

Run: `python3 -m unittest discover -s tests -p 'test_*.py'`

Expected: all tests pass; baseline was 380 tests before video additions.

- [ ] **Step 2: Run syntax and import checks**

Run: `python3 -m compileall -q main.py app_core scripts tests`

Run: `node --check static/video_media.js`

Run: `python3 -c 'import main; print(sorted(main.TASK_CONFIGS))'`

Expected: every command exits 0 and task types print `['T2I', 'T2V', 'TI2I', 'TI2V']` in dictionary sort order.

- [ ] **Step 3: Start an isolated local server**

Run with a task-specific database/root override fixture or copied temporary workspace so the user's untracked `database.db` is not mutated. Start `uvicorn main:app` on an unused localhost port and confirm `/api/task_types` returns four task types.

Expected: server reaches ready state and the API payload includes image/video capabilities.

- [ ] **Step 4: Perform browser walkthrough with network and interaction checks**

Use the in-app browser control skill. Log in with a temporary evaluator and verify:

1. T2I and TI2I setup controls and desktop layouts remain unchanged.
2. T2V/TI2V dimension chips default to all selected and prevent an empty selection.
3. Equal sets resume; superset confirmation restarts; subset and incomparable selections show blocking errors without deleting results.
4. T2V renders two video panes; TI2V renders reference image between two video panes.
5. Controls show on pointer/focus and hide on pointer leave.
6. Sync on mirrors play/pause/seek; Sync off keeps videos independent.
7. Frame tools reject playing videos and operate on paused frames.
8. Video dashboard dimension cards occupy two rows while T2I/TI2I cards retain their prior row.
9. Detail and bad-case list network requests fetch WebP thumbnails only; MP4 requests begin only after HD preview opens.
10. Closing HD preview stops playback and no video request continues in the background.

- [ ] **Step 5: Audit every approved requirement and inspect the diff**

Run: `git diff 07a0740...HEAD --check`

Run: `git status --short`

Review `docs/superpowers/specs/2026-07-28-video-evaluation-design.md` line by line and map each requirement to a passing test or browser observation. Confirm `database.db` remains untracked and unstaged.

Expected: no whitespace errors, no unrelated files, and every requirement has evidence.

- [ ] **Step 6: Commit only direct verification repairs, if any**

If verification required a code repair, first add and witness a regression test against the pre-repair behavior. Stage only the named regression-test file and the directly repaired source files shown by `git diff --name-only`, verify that `database.db` is absent from `git diff --cached --name-only`, and commit with message `fix: address video evaluation verification findings`. If no repair was required, do not create an empty commit.
