# Export, TI2I Bad-Case, and Prompt Preview Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate existing export detail Sheets with evaluated rows, show TI2I bad cases as reference/result pairs, and place Prompt text above images in both high-resolution preview surfaces.

**Architecture:** Keep the current workbook and preview-controller structures. Fix the export record union at its source, add a dedicated bad-case preview payload normalized by the existing dashboard renderer, and make each preview header a flow-layout region that owns a safely assigned Prompt text node.

**Tech Stack:** Python 3, `unittest`, `openpyxl`, server-rendered HTML/CSS, vanilla JavaScript, Node.js runtime probes, headless Chrome geometry probes.

## Global Constraints

- Preserve the existing `Overall + detail Sheets` workbook structure, Sheet names, and columns.
- Do not copy Overall judgments into unevaluated dimension cells.
- TI2I bad-case preview contains only reference and the selected bad-case result; T2I remains one image.
- Prompt is assigned through `textContent`, wraps in the header, and never overlays an image.
- Add no dependency and do not change database data, APIs, filters, statistics, or pagination.
- Preserve the user's uncommitted `.gitignore` and untracked `database.db`.

---

### Task 1: Include evaluated records in existing export detail Sheets

**Files:**
- Modify: `app_core/export_service.py:516-559`
- Test: `tests/test_export_workbook.py`

**Interfaces:**
- Consumes: `overall_rows: list`, `dimension_rows: dict[str, list]`, and row key `id`.
- Produces: `detail_row_ids: set[int]` containing records selected by Overall or any requested dimension; `_scene_detail_values()` continues to mark only real dimension matches.

- [ ] **Step 1: Write the failing regression test**

Add a test that builds a TI2I workbook from one `eval_mode="overall"` record whose `fidelity` is `None`, then asserts the existing `portrait` Sheet contains a data row while its three fidelity cells remain blank:

```python
@patch("app_core.export_service.get_prompt_text", return_value="portrait prompt")
def test_overall_evaluated_row_is_written_to_existing_scene_detail_without_fabricating_dimensions(self, _prompt):
    request = ExportRequest(task_type="TI2I", v1="D", v2="E", dimensions=["fidelity"])
    rows = [make_row(
        1, task_type="TI2I", v_a="D", v_b="E", scene="portrait",
        eval_mode="overall", overall="D", fidelity=None,
    )]

    sheet = build_workbook(request, rows)["portrait"]
    headers = [cell.value for cell in sheet[2]]
    fidelity_start = headers.index("D 胜") + 1

    self.assertEqual(sheet.max_row, 3)
    self.assertEqual(sheet.cell(3, headers.index("图片名") + 1).value, "image-1.png")
    self.assertEqual(
        [sheet.cell(3, column).value for column in range(fidelity_start, fidelity_start + 3)],
        [None, None, None],
    )
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m unittest tests.test_export_workbook.ExportWorkbookTests.test_overall_evaluated_row_is_written_to_existing_scene_detail_without_fabricating_dimensions -v
```

Expected: FAIL because `portrait.max_row` is `2`; the Sheet contains only its two header rows.

- [ ] **Step 3: Implement the minimal row-union fix**

Replace the dimension-only ID set in `build_workbook()` with the union of Overall and dimension-selected IDs:

```python
detail_row_ids = {row["id"] for row in overall_rows}
detail_row_ids.update(
    row["id"]
    for rows_for_dimension in dimension_rows.values()
    for row in rows_for_dimension
)
```

Keep `matching_row_ids` unchanged so `_scene_detail_values()` does not invent dimension judgments.

- [ ] **Step 4: Verify GREEN and export regressions**

Run:

```bash
python3 -m unittest tests.test_export_workbook tests.test_export_filtering -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the export fix**

```bash
git add app_core/export_service.py tests/test_export_workbook.py
git commit -m "fix: include evaluated rows in export details"
```

---

### Task 2: Show TI2I bad cases as reference/result preview pairs

**Files:**
- Modify: `templates/dashboard.html:2506-2598`
- Test: `tests/test_dashboard_image_preview_ui.py`

**Interfaces:**
- Consumes: bad-case row fields `task_type`, `ref_img`, `prompt`, `model`, `scene`, and `filename`.
- Produces: `buildBadCasePreviewPayload(row, resultSrc) -> object`; `normalizeDashboardPreview(payload)` returns one result pane for T2I/missing-reference or two panes (`reference`, `result`) for TI2I.

- [ ] **Step 1: Write failing bad-case payload tests**

Extract and execute `buildBadCasePreviewPayload()` plus `normalizeDashboardPreview()` in Node. Assert:

```python
self.assertEqual([pane["id"] for pane in result["ti2i"]["panes"]], ["reference", "result"])
self.assertEqual([pane["src"] for pane in result["ti2i"]["panes"]], ["ref.jpg", "bad.jpg"])
self.assertTrue(result["ti2i"]["showSync"])
self.assertTrue(result["ti2i"]["showCompare"])
self.assertEqual([pane["id"] for pane in result["t2i"]["panes"]], ["single"])
self.assertEqual([pane["id"] for pane in result["missingRef"]["panes"]], ["single"])
```

Also assert the bad-case click handler calls `openPreview(buildBadCasePreviewPayload(row, src))` rather than `openSinglePreview()`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_ti2i_bad_case_preview_contains_reference_and_selected_result tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_bad_case_click_uses_bad_case_payload -v
```

Expected: FAIL because the helper does not exist and the current click path is single-image only.

- [ ] **Step 3: Implement the dedicated payload and normalization branch**

Add:

```javascript
function buildBadCasePreviewPayload(row, resultSrc) {
    return {
        badCase: true,
        mode: row.task_type || state.taskType,
        ref: row.ref_img,
        result: resultSrc,
        resultLabel: row.model,
        prompt: row.prompt || ""
    };
}
```

At the start of `normalizeDashboardPreview(payload)`, after the explicit single branch, add:

```javascript
if (payload.badCase) {
    if (payload.mode === "TI2I" && payload.ref) {
        return {
            kind: "t2i",
            panes: [
                { id: "reference", src: payload.ref, label: "参考图" },
                { id: "result", src: payload.result, label: payload.resultLabel }
            ],
            prompt: payload.prompt || "",
            showSync: true,
            showCompare: true
        };
    }
    return {
        kind: "single",
        panes: [{ id: "single", src: payload.result, label: payload.resultLabel }],
        prompt: payload.prompt || "",
        showSync: false,
        showCompare: false
    };
}
```

Change the bad-case image click to:

```javascript
image.addEventListener("click", () => openPreview(buildBadCasePreviewPayload(row, src)));
```

- [ ] **Step 4: Verify GREEN and existing preview behavior**

Run:

```bash
python3 -m unittest tests.test_dashboard_image_preview_ui -v
```

Expected: all tests PASS after replacing the obsolete single-image assertion with the new contract.

- [ ] **Step 5: Commit the TI2I bad-case fix**

```bash
git add templates/dashboard.html tests/test_dashboard_image_preview_ui.py
git commit -m "fix: preview TI2I bad cases with references"
```

---

### Task 3: Place Prompt above dashboard and evaluation preview images

**Files:**
- Modify: `templates/dashboard.html:367-470,1057-1070,2318-2346,2558-2803`
- Modify: `templates/index.html:673-721,938-954,1880-1960`
- Test: `tests/test_dashboard_image_preview_ui.py`
- Test: `tests/test_evaluation_preview_ui.py`

**Interfaces:**
- Consumes: dashboard normalized payload property `prompt` and evaluation `state.currentTask.prompt`.
- Produces: dashboard node `#dashboard-preview-prompt`, evaluation node `#lightbox-prompt`, and `syncLightboxPrompt()`; both use `textContent` and `.hidden`.

- [ ] **Step 1: Write failing dashboard Prompt propagation and layout tests**

Add tests asserting `buildPreviewPayload()` returns `prompt: row.prompt || ""`, both normal and bad-case normalized payloads retain Prompt, and `openDashboardPreview()` assigns it through `promptNode.textContent`. Add a headless geometry test with a multiline Prompt that asserts:

```python
self.assertLessEqual(result["headBottom"], result["gridTop"])
self.assertFalse(result["overlapsImage"])
```

The probe must use production markup with `.dashboard-preview-head`, `#dashboard-preview-prompt`, `.dashboard-preview-content`, and `.dashboard-preview-grid`.

- [ ] **Step 2: Write failing evaluation Prompt synchronization and layout tests**

Add tests asserting the lightbox contains `id="lightbox-prompt"`, `syncLightboxPrompt()` assigns `state.currentTask.prompt` via `textContent`, toggles `.hidden`, and is called before the lightbox is displayed. Verify CSS keeps `.lightbox-head` in grid row 1 and `#lightbox-grid` in grid row 2.

- [ ] **Step 3: Run Prompt tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_dashboard_preview_prompt_is_propagated_and_written_as_text tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_dashboard_prompt_header_does_not_overlap_images tests.test_evaluation_preview_ui.EvaluationPreviewUiTests.test_lightbox_prompt_is_synchronized_as_header_text -v
```

Expected: FAIL because neither preview has a Prompt header node or synchronization function.

- [ ] **Step 4: Implement the dashboard flow-layout header and Prompt assignment**

Change the stage to a column flex layout, make the header a normal-flow flex row, and wrap the existing toolbar/grid in a positioned flex child:

```html
<div class="dashboard-preview-head">
    <div class="dashboard-preview-heading">
        <strong id="dashboard-preview-title">高清预览</strong>
        <div id="dashboard-preview-prompt" class="preview-prompt hidden"></div>
    </div>
    <button class="btn btn-outline" type="button" data-preview-close>关闭</button>
</div>
<div class="dashboard-preview-content">
    <div id="dashboard-preview-toolbar"></div>
    <div class="dashboard-preview-grid single" id="image-preview"></div>
</div>
```

Use CSS with `.dashboard-preview-stage { display:flex; flex-direction:column; }`, `.dashboard-preview-head { position:relative; inset:auto; flex:0 0 auto; }`, `.dashboard-preview-content { position:relative; flex:1 1 auto; min-height:0; }`, and `.preview-prompt { white-space:pre-wrap; overflow-wrap:anywhere; max-height:20dvh; overflow:auto; }`. Keep the grid at `height:100%` inside the content wrapper.

Add `prompt: row.prompt || ""` to `buildPreviewPayload()`. Preserve Prompt in every `normalizeDashboardPreview()` return. In `openDashboardPreview()`:

```javascript
const promptNode = document.getElementById("dashboard-preview-prompt");
promptNode.textContent = normalized.prompt || "";
promptNode.classList.toggle("hidden", !normalized.prompt);
```

Clear and hide the node in `closeImagePreview()`.

- [ ] **Step 5: Implement evaluation lightbox Prompt synchronization**

Add `<div id="lightbox-prompt" class="lightbox-prompt hidden"></div>` beneath the lightbox title/help text. Add:

```javascript
function syncLightboxPrompt() {
    const promptNode = document.getElementById("lightbox-prompt");
    const prompt = state.currentTask?.prompt || "";
    promptNode.textContent = prompt;
    promptNode.classList.toggle("hidden", !prompt);
}
```

Call `syncLightboxPrompt()` in `openLightbox()` before adding `.open`. Style `.lightbox-prompt` with `white-space:pre-wrap`, `overflow-wrap:anywhere`, and a bounded scrollable height; the existing grid rows then keep it above `#lightbox-grid`.

- [ ] **Step 6: Verify GREEN and all preview regressions**

Run:

```bash
python3 -m unittest tests.test_dashboard_image_preview_ui tests.test_evaluation_preview_ui -v
```

Expected: all tests PASS at desktop and narrow layouts.

- [ ] **Step 7: Commit the Prompt preview fix**

```bash
git add templates/dashboard.html templates/index.html tests/test_dashboard_image_preview_ui.py tests/test_evaluation_preview_ui.py
git commit -m "fix: show prompts above high-resolution previews"
```

---

### Task 4: Final verification

**Files:**
- Verify only; no planned production changes.

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: evidence that Python, JavaScript, export, and preview behavior all pass together.

- [ ] **Step 1: Run the complete Python test suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests PASS.

- [ ] **Step 2: Compile Python and parse every inline template script**

```bash
python3 -m compileall -q main.py app_core tests
node -e 'const fs=require("fs"),vm=require("vm"); for (const f of fs.readdirSync("templates").filter(x=>x.endsWith(".html"))) { const s=fs.readFileSync("templates/"+f,"utf8"); for (const m of s.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)) new vm.Script(m[1], {filename:f}); } console.log("templates js ok")'
```

Expected: Python exits `0`; Node prints `templates js ok`.

- [ ] **Step 3: Check patch hygiene and user-owned files**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; `.gitignore` and `database.db` remain untouched and uncommitted.
