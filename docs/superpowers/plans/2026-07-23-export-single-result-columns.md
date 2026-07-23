# Export Single Result Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Represent Overall and every selected evaluation dimension as one result column containing the winning model name or `tie` in each existing scene detail Sheet.

**Architecture:** Keep the current workbook, Sheet names, two-level headers, and row-selection filters. Build one ordered result-dimension list (`overall` conditionally followed by selected dimensions), render it under a shared “评测结果” group, and use the existing per-dimension matching ID sets to decide whether each raw database result is written or left blank.

**Tech Stack:** Python 3, `unittest`, `openpyxl`.

## Global Constraints

- Preserve the existing `Overall + detail Sheets` workbook structure, Sheet names, two-level headers, sample fields, image fields, and bad-case fields.
- The first-level result group is exactly `评测结果`; second-level headers are `整体` when `eval_modes` contains `overall`, followed by the selected labels from `DIM_LABELS` in task-config order.
- Each result dimension occupies exactly one column whose non-empty value is the real model name or `tie`; do not write one-hot `1` markers or fabricate results.
- Keep the current global and per-dimension result-filter semantics: a record not in that dimension's matching ID set has a blank cell.
- Add no dependency and do not change APIs, database data/schema, image archives, preview UI, filters, statistics, or pagination.
- Do not add or commit `database.db`.

---

### Task 1: Collapse Overall and dimension judgments into single result columns

**Files:**
- Modify: `app_core/export_service.py:377-488,530-557`
- Test: `tests/test_export_workbook.py`

**Interfaces:**
- Consumes: `dimensions: list[str]`, `request.eval_modes: list[str]`, row result fields (`overall`, `aesthetic`, `logic`, `consistency`, `fidelity`), and `matching_row_ids: dict[str, set[int]]`.
- Produces: `_selected_result_dimensions(dimensions, request) -> list[str]`; a shared `评测结果` group with one header/value per returned key; `matching_row_ids` containing `overall` plus selected dimension ID sets.

- [ ] **Step 1: Replace the three-column expectations with failing single-column behavior tests**

Update the workbook tests to assert these exact contracts:

```python
@patch("app_core.export_service.get_prompt_text", return_value="portrait prompt")
def test_overall_and_dimensions_use_single_raw_result_columns(self, _prompt):
    request = ExportRequest(
        task_type="TI2I", v1="D", v2="E", dimensions=["fidelity"],
        eval_modes=["full", "overall"],
    )
    rows = [
        make_row(1, task_type="TI2I", v_a="D", v_b="E", scene="portrait", eval_mode="overall", overall="D", fidelity=None),
        make_row(2, task_type="TI2I", v_a="D", v_b="E", scene="portrait", eval_mode="full", overall="tie", fidelity="E"),
    ]

    sheet = build_workbook(request, rows)["portrait"]
    groups = [cell.value for cell in sheet[1]]
    headers = [cell.value for cell in sheet[2]]

    self.assertEqual(groups.count("评测结果"), 1)
    self.assertEqual(headers.count("整体"), 1)
    self.assertEqual(headers.count("保真度"), 1)
    self.assertNotIn("D 胜", headers)
    self.assertNotIn("平局", headers)
    self.assertNotIn("E 胜", headers)
    self.assertEqual(
        [[sheet.cell(row, headers.index(name) + 1).value for name in ("整体", "保真度")] for row in (3, 4)],
        [["D", None], ["tie", "E"]],
    )
```

Add the mode-boundary regression:

```python
@patch("app_core.export_service.get_prompt_text", return_value="portrait prompt")
def test_full_only_export_omits_overall_result_column(self, _prompt):
    request = ExportRequest(
        task_type="TI2I", v1="D", v2="E", dimensions=["fidelity"], eval_modes=["full"],
    )
    rows = [make_row(1, task_type="TI2I", v_a="D", v_b="E", scene="portrait", overall="D", fidelity="tie")]

    sheet = build_workbook(request, rows)["portrait"]
    headers = [cell.value for cell in sheet[2]]

    self.assertNotIn("整体", headers)
    self.assertEqual(sheet.cell(3, headers.index("保真度") + 1).value, "tie")
```

Update existing grouped-detail, TI2I fidelity, independent-result-filter, formula-safety, and Prompt-cache tests only where their column lookup or group expectations still assume three one-hot columns. Preserve their original behavioral assertions.

- [ ] **Step 2: Run the export workbook module and verify RED**

Run:

```bash
python3 -m unittest tests.test_export_workbook -v
```

Expected: the new tests FAIL because the detail Sheet still exposes `D 胜 / 平局 / E 胜`, has no `整体` result column, and writes one-hot `1` markers.

- [ ] **Step 3: Add the ordered result-dimension helper**

Add beside `_scene_detail_groups()`:

```python
def _selected_result_dimensions(dimensions: list[str], request: ExportRequest) -> list[str]:
    result = ["overall"] if "overall" in request.eval_modes else []
    result.extend(dimensions)
    return result
```

- [ ] **Step 4: Render one shared result group and one raw value per dimension**

In `_scene_detail_groups()`, replace the per-dimension three-column groups with:

```python
    result_dimensions = _selected_result_dimensions(dimensions, request)
    if result_dimensions:
        groups.append(("评测结果", [DIM_LABELS[dimension] for dimension in result_dimensions]))
```

In `_scene_detail_values()`, replace the one-hot loop with:

```python
    for dimension in _selected_result_dimensions(dimensions, request):
        values.append(row[dimension] if row_id in matching_row_ids[dimension] else None)
```

In `build_workbook()`, include Overall in the matching map and derive detail IDs from the complete map:

```python
    matching_row_ids = {"overall": {row["id"] for row in overall_rows}}
    matching_row_ids.update({
        dimension: {row["id"] for row in rows_for_dimension}
        for dimension, rows_for_dimension in dimension_rows.items()
    })
    detail_row_ids = set().union(*matching_row_ids.values()) if matching_row_ids else set()
```

Do not modify `filter_rows()`; its result-filter behavior remains the source of truth for blank versus populated cells.

- [ ] **Step 5: Verify GREEN and all export regressions**

Run:

```bash
python3 -m unittest tests.test_export_workbook tests.test_export_filtering tests.test_export_archive tests.test_dashboard_export_ui -v
```

Expected: all tests PASS; workbook tests confirm raw model/`tie` values, formula-safety tests confirm external model names cannot create formulas, and archive/UI contracts remain unchanged.

- [ ] **Step 6: Commit the export format fix**

```bash
git add app_core/export_service.py tests/test_export_workbook.py
git commit -m "fix: export judgments in single result columns"
```

---

### Task 2: Final verification

**Files:**
- Verify only; no planned production changes.

**Interfaces:**
- Consumes: Task 1 commit.
- Produces: current-HEAD evidence for all Python tests, template JavaScript parsing, and patch hygiene.

- [ ] **Step 1: Run the complete suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests PASS.

- [ ] **Step 2: Compile and check templates**

```bash
python3 -m compileall -q main.py app_core tests
sed -n '/^[[:space:]]*<script>$/,/^[[:space:]]*<\/script>$/p' templates/dashboard.html | sed '1d;$d' | node --check -
sed -n '/^[[:space:]]*<script>$/,/^[[:space:]]*<\/script>$/p' templates/index.html | sed '1d;$d' | node --check -
```

Expected: every command exits `0` with no syntax errors.

- [ ] **Step 3: Check patch and workspace hygiene**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only the intentionally untracked local `database.db` may appear.
