# Evaluation Dashboard Conflict Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the video structure-reasonableness dimension, full-screen evaluation preview, complete-data detail sorting, conflict detection/visibility, conflict reliability statistics, and conflict-excluded analytics without changing raw detail visibility.

**Architecture:** Add one schema-backed score dimension, then centralize sample/evaluator identity and per-dimension conflict detection in `app_core/dashboard_service.py`. Dashboard, worker, and ranking services reuse the same raw-query conflict index; the browser receives conflict metadata, sorts all filtered detail rows before pagination, and uses a single checkbox to refetch conflict-excluded aggregate views while preserving raw detail rows.

**Tech Stack:** Python 3.9, FastAPI, SQLite, Pydantic, Jinja/vanilla JavaScript/CSS, `unittest`, Node.js DOM-free JavaScript probes, optional headless Chrome geometry probes.

## Global Constraints

- Preserve the approved definition of a conflict: for one canonical sample and one dimension, at least two distinct evaluator identities collectively contain both an A-winner vote and a B-winner vote. Ignore ties and bad-case tags.
- Prefer `user_id` as evaluator identity; use a namespaced `worker` fallback only when `user_id` is absent.
- Use the canonical sample key `(task_type, sorted(v_a, v_b), scene, filename)` everywhere.
- Exclude conflicts per dimension only. A sample conflicted on `overall` remains eligible for every non-conflicted dimension.
- Keep `sample_count` and `conflict_sample_count` based on raw rows even when aggregate vote counts exclude conflicts.
- Keep all raw rows in the detail modal. Filtering conflicts applies only to overview, scene, worker, and ranking aggregates.
- Sort the complete filtered detail dataset before slicing the current page.
- Keep missing timestamps last in both ascending and descending time sorts.
- Do not introduce video elements into dashboard detail rows; existing first-frame image behavior remains unchanged.
- Preserve the user-owned untracked `/Users/baobinglei/code/ab_test/database.db`.
- Use `apply_patch` for source edits and run the named RED test before each production change.

---

## Task 1: Persist the `structure_reasonableness` video score

**Files:**

- Modify: `/Users/baobinglei/code/ab_test/app_core/config.py:59-134`
- Modify: `/Users/baobinglei/code/ab_test/app_core/schemas.py:22-45`
- Modify: `/Users/baobinglei/code/ab_test/app_core/database.py:1-138`
- Modify: `/Users/baobinglei/code/ab_test/app_core/task_service.py:799-840`
- Test: `/Users/baobinglei/code/ab_test/tests/test_video_config_schema.py:18-94`
- Test: `/Users/baobinglei/code/ab_test/tests/test_video_task_service.py:67-153`

- [ ] **Step 1: Extend the configuration and schema contract tests**

Update the expected dimension order for both video task types and assert that the submission schema exposes the new field:

```python
# tests/test_video_config_schema.py imports
from app_core.config import DIM_LABELS, TASK_CONFIGS
from app_core.schemas import VoteSubmit

expected_t2v_dashboard = [
    "overall",
    "text_consistency",
    "structure_reasonableness",
    "motion_reasonableness",
    "dynamism",
    "physical_plausibility",
    "visual_quality",
]
expected_t2v_eval = expected_t2v_dashboard[1:]
expected_ti2v_dashboard = expected_t2v_dashboard + ["image_consistency"]
expected_ti2v_eval = expected_t2v_eval + ["image_consistency"]

self.assertEqual(TASK_CONFIGS["T2V"]["eval_dims"], expected_t2v_eval)
self.assertEqual(TASK_CONFIGS["T2V"]["dashboard_dims"], expected_t2v_dashboard)
self.assertEqual(TASK_CONFIGS["TI2V"]["eval_dims"], expected_ti2v_eval)
self.assertEqual(TASK_CONFIGS["TI2V"]["dashboard_dims"], expected_ti2v_dashboard)
self.assertEqual(DIM_LABELS["structure_reasonableness"], "结构合理性")
self.assertIn("structure_reasonableness", VoteSubmit.__fields__)
```

In the selected-dimension persistence test, start a T2V task with only the new dimension and verify its value is stored:

```python
# Add this default beside text_consistency in VideoTaskServiceTests.vote:
"structure_reasonableness": "right",

self.start(["structure_reasonableness"])
task_id = self.task_id()
submit_vote(
    self.vote(
        task_id,
        ["structure_reasonableness"],
        structure_reasonableness="right",
    ),
    1,
    "admin",
)
conn = connect()
row = conn.execute(
    "SELECT structure_reasonableness, selected_dimensions "
    "FROM results_log WHERE task_id=?",
    (task_id,),
).fetchone()
conn.close()
self.assertEqual(row[0], "test_B_default")
self.assertEqual(json.loads(row[1]), ["structure_reasonableness"])
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_video_config_schema tests.test_video_task_service
```

Expected: failures because the configuration, Pydantic model, SQLite column, and INSERT statement do not yet contain `structure_reasonableness`.

- [ ] **Step 3: Add the dimension to configuration and request schema**

Apply these exact ordering changes:

```python
# app_core/config.py, TASK_CONFIGS["T2V"]
"eval_dims": [
    "text_consistency",
    "structure_reasonableness",
    "motion_reasonableness",
    "dynamism",
    "physical_plausibility",
    "visual_quality",
],
"dashboard_dims": [
    "overall",
    "text_consistency",
    "structure_reasonableness",
    "motion_reasonableness",
    "dynamism",
    "physical_plausibility",
    "visual_quality",
],

# TASK_CONFIGS["TI2V"] uses the same two lists and appends
# "image_consistency" to both of them.

"structure_reasonableness": "结构合理性",

VIDEO_SCORE_DIMENSIONS = (
    "text_consistency",
    "structure_reasonableness",
    "motion_reasonableness",
    "dynamism",
    "physical_plausibility",
    "visual_quality",
    "image_consistency",
)
```

```python
# app_core/schemas.py, immediately after text_consistency
structure_reasonableness: Optional[str] = None
```

- [ ] **Step 4: Add the SQLite column and submit-value binding**

Make database migration coverage derive from the canonical tuple:

```python
# app_core/database.py
from .config import DB_PATH, VIDEO_SCORE_DIMENSIONS

for column in VIDEO_SCORE_DIMENSIONS:
    ensure_column(cursor, "results_log", column, "TEXT")
```

Add this nullable column to the new-database `CREATE TABLE results_log` statement between text and motion:

```sql
structure_reasonableness TEXT,
```

Add the same column and bound value to the normal vote INSERT:

```python
INSERT INTO results_log (
    task_id, eval_mode, task_type, v_a, v_b, scene, filename,
    overall, aesthetic, logic, consistency, fidelity,
    text_consistency, structure_reasonableness,
    motion_reasonableness, dynamism, physical_plausibility,
    visual_quality, image_consistency,
    selected_dimensions,
    worker, timestamp, duration_seconds, user_id,
    bad_case_tags_a, bad_case_tags_b,
    bad_case_categories_a, bad_case_categories_b
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

```python
(
    vote.task_id,
    eval_mode,
    task_type,
    task_v_a,
    task_v_b,
    task_scene,
    task_filename,
    score_values["overall"],
    score_values["aesthetic"],
    score_values["logic"],
    score_values["consistency"],
    score_values["fidelity"],
    score_values["text_consistency"],
    score_values["structure_reasonableness"],
    score_values["motion_reasonableness"],
    score_values["dynamism"],
    score_values["physical_plausibility"],
    score_values["visual_quality"],
    score_values["image_consistency"],
    json.dumps(selected_dimensions, ensure_ascii=False),
    worker,
    now_beijing_iso(),
    vote.duration_seconds,
    user_id,
    json.dumps(tags_a, ensure_ascii=False),
    json.dumps(tags_b, ensure_ascii=False),
    json.dumps(categories_from_tags(tags_a), ensure_ascii=False),
    json.dumps(categories_from_tags(tags_b), ensure_ascii=False),
)
```

Also insert `structure_reasonableness` after `text_consistency` in the skip-row column list, add one `?` in that position, and add one `None` in the corresponding tuple. The skip INSERT still stores 12 null score values, then `selected_dimensions`, `worker`, `timestamp`, literal `skipped=1`, and `user_id`.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
python3 -m unittest tests.test_video_config_schema tests.test_video_task_service
```

Expected: all tests pass.

Commit:

```bash
git add app_core/config.py app_core/schemas.py app_core/database.py app_core/task_service.py tests/test_video_config_schema.py tests/test_video_task_service.py
git commit -m "feat: persist video structure reasonableness scores"
```

---

## Task 2: Carry the new dimension through evaluation, detail, history, and export

**Files:**

- Modify: `/Users/baobinglei/code/ab_test/templates/index.html:1325-1403,2168-2209`
- Modify: `/Users/baobinglei/code/ab_test/app_core/dashboard_service.py:149-188`
- Modify: `/Users/baobinglei/code/ab_test/app_core/user_service.py:87-127`
- Modify: `/Users/baobinglei/code/ab_test/README.md`
- Test: `/Users/baobinglei/code/ab_test/tests/test_video_evaluation_ui.py:722-789`
- Test: `/Users/baobinglei/code/ab_test/tests/test_video_dashboard.py`
- Test: `/Users/baobinglei/code/ab_test/tests/test_video_export.py:20-233`

- [ ] **Step 1: Add failing consumer tests**

Extend the evaluation payload source assertion:

```python
source = self.function_source("submitVote", "skipTask")
expected_fields = [
    "text_consistency",
    "structure_reasonableness",
    "motion_reasonableness",
    "dynamism",
    "physical_plausibility",
    "visual_quality",
    "image_consistency",
]
for field in expected_fields:
    self.assertIn(f"{field}: currentVotes.{field} || null", source)
```

Add `"structure_reasonableness": None` after `text_consistency` in both video row fixtures, then assert detail/history/export behavior:

```python
self.assertEqual(detail["structure_reasonableness"], "B")
self.assertEqual(detail["scores"]["structure_reasonableness"], "B")
self.assertEqual(history[0]["structure_reasonableness"], "B")
with patch("app_core.export_service.fetch_base_rows", return_value=[]):
    options = get_export_options("T2V", "B", "A")
self.assertIn(
    {"key": "structure_reasonableness", "label": "结构合理性"},
    options["dimensions"],
)
```

For the workbook test, request `structure_reasonableness` and assert its header and cell value:

```python
request = ExportRequest(
    task_type="T2V",
    v1="A",
    v2="B",
    dimensions=["structure_reasonableness"],
    eval_modes=["selected"],
)
sheet = build_workbook(
    request,
    [make_video_row(1, structure_reasonableness="B")],
)["motion"]
headers = [cell.value for cell in sheet[2]]
structure_column = headers.index("结构合理性") + 1
self.assertEqual(sheet.cell(3, structure_column).value, "B")
```

- [ ] **Step 2: Run the consumer tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_video_evaluation_ui tests.test_video_dashboard tests.test_video_export
```

Expected: payload, detail projection, history projection, and fixture/order assertions fail.

- [ ] **Step 3: Add the evaluation payload and detail projection**

```javascript
// templates/index.html, immediately after text_consistency
structure_reasonableness: currentVotes.structure_reasonableness || null,
```

The dimension chips already render from `TASK_CONFIGS`, so do not add hard-coded HTML controls.

```python
# app_core/dashboard_service.py, in each detail response object
"structure_reasonableness": optional_row_value(row, "structure_reasonableness"),
```

The existing `scores` dictionary is driven by task configuration; verify it includes the new key rather than duplicating a second hard-coded list.

- [ ] **Step 4: Shift history indexes and document the field**

Add the field to the history SELECT between text and motion, then use this exact index mapping:

```python
"text_consistency": row[10],
"structure_reasonableness": row[11],
"motion_reasonableness": row[12],
"dynamism": row[13],
"physical_plausibility": row[14],
"visual_quality": row[15],
"image_consistency": row[16],
"selected_dimensions": safe_load_json_list(row[17]),
"timestamp": row[18],
"duration_seconds": row[19],
"skipped": row[20],
```

Update both README T2V dimension lists to place `结构合理性` after `文本一致性`, change the T2V count from six to seven, and retain TI2V’s final `图像一致性` dimension. No production export-service change should be needed because export dimensions and labels are configuration-driven.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 -m unittest tests.test_video_evaluation_ui tests.test_video_dashboard tests.test_video_export
```

Expected: all tests pass.

Commit:

```bash
git add templates/index.html app_core/dashboard_service.py app_core/user_service.py README.md tests/test_video_evaluation_ui.py tests/test_video_dashboard.py tests/test_video_export.py
git commit -m "feat: expose structure reasonableness across video workflows"
```

---

## Task 3: Build one per-dimension conflict index and annotate overview/detail data

**Files:**

- Create: `/Users/baobinglei/code/ab_test/tests/test_dashboard_conflicts.py`
- Modify: `/Users/baobinglei/code/ab_test/app_core/dashboard_service.py:34-188`
- Modify: `/Users/baobinglei/code/ab_test/tests/test_four_way_dashboard.py`
- Modify: `/Users/baobinglei/code/ab_test/tests/test_video_dashboard.py`

- [ ] **Step 1: Create representative conflict tests**

Use a complete row factory so sample identity is testable:

```python
def result_row(
    row_id,
    worker,
    filename,
    overall,
    *,
    user_id=None,
    logic=None,
    scene="scene-1",
    v_a="model-a",
    v_b="model-b",
):
    return {
        "id": row_id,
        "task_type": "T2I",
        "eval_mode": "full",
        "v_a": v_a,
        "v_b": v_b,
        "scene": scene,
        "filename": filename,
        "overall": overall,
        "aesthetic": None,
        "logic": logic,
        "consistency": None,
        "fidelity": None,
        "text_consistency": None,
        "structure_reasonableness": None,
        "motion_reasonableness": None,
        "dynamism": None,
        "physical_plausibility": None,
        "visual_quality": None,
        "image_consistency": None,
        "selected_dimensions": "[]",
        "worker": worker,
        "user_id": user_id,
        "timestamp": "2026-08-13T10:00:00+08:00",
        "duration_seconds": 1,
        "skipped": 0,
        "bad_case_tags_a": "[]",
        "bad_case_tags_b": "[]",
        "bad_case_categories_a": "[]",
        "bad_case_categories_b": "[]",
    }
```

Cover evaluator identity, ignored values, and key isolation with explicit assertions:

```python
def conflict_dimensions(*rows):
    index = build_conflict_index(rows, ["overall", "logic"])
    return index.get(sample_identity(rows[0]), set())


def test_distinct_evaluators_with_opposite_winners_conflict(self):
    rows = (
        result_row(1, "alice", "one.png", "model-a", user_id=10),
        result_row(2, "bob", "one.png", "model-b", user_id=20),
    )
    self.assertEqual(conflict_dimensions(*rows), {"overall"})


def test_ties_bad_cases_and_one_identity_do_not_conflict(self):
    ties = (
        result_row(1, "alice", "tie.png", "tie_good", user_id=10),
        result_row(2, "bob", "tie.png", "tie_bad", user_id=20),
    )
    ties[0]["bad_case_tags_a"] = '["模糊失焦"]'
    self.assertEqual(conflict_dimensions(*ties), set())

    duplicate_identity = (
        result_row(3, "old-name", "same-user.png", "model-a", user_id=30),
        result_row(4, "new-name", "same-user.png", "model-b", user_id=30),
    )
    self.assertEqual(conflict_dimensions(*duplicate_identity), set())


def test_missing_user_id_uses_worker_identity(self):
    rows = (
        result_row(1, "alice", "fallback.png", "model-a"),
        result_row(2, "bob", "fallback.png", "model-b"),
    )
    self.assertEqual(conflict_dimensions(*rows), {"overall"})


def test_sample_and_dimension_boundaries_are_isolated(self):
    base = result_row(1, "alice", "one.png", "model-a", user_id=1, logic="model-a")
    for changed in (
        result_row(2, "bob", "two.png", "model-b", user_id=2, logic="model-a"),
        result_row(3, "bob", "one.png", "model-b", user_id=2, logic="model-a", scene="scene-2"),
        result_row(4, "bob", "one.png", "other-b", user_id=2, logic="model-a", v_b="other-b"),
    ):
        with self.subTest(changed=changed):
            index = build_conflict_index([base, changed], ["overall", "logic"])
            self.assertEqual(index, {})

    same_sample = result_row(
        5, "bob", "one.png", "model-b", user_id=2, logic="model-a"
    )
    index = build_conflict_index([base, same_sample], ["overall", "logic"])
    self.assertEqual(index[sample_identity(base)], {"overall"})
```

The key per-dimension assertion should use two rows for the same sample:

```python
rows = [
    result_row(1, "alice", "one.png", "model-a", user_id=10, logic="model-a"),
    result_row(2, "bob", "one.png", "model-b", user_id=20, logic="model-a"),
]
index = build_conflict_index(rows, ["overall", "logic"])
self.assertEqual(index[sample_identity(rows[0])], {"overall"})

raw = dimension_stats(
    rows, "overall", "model-a", "model-b", conflict_index=index
)
self.assertEqual(raw["sample_count"], 1)
self.assertEqual(raw["conflict_sample_count"], 1)
self.assertEqual(raw["total"], 2)

filtered = dimension_stats(
    rows,
    "overall",
    "model-a",
    "model-b",
    conflict_index=index,
    exclude_conflicts=True,
)
self.assertEqual(filtered["sample_count"], 1)
self.assertEqual(filtered["conflict_sample_count"], 1)
self.assertEqual(filtered["total"], 0)

logic = dimension_stats(
    rows,
    "logic",
    "model-a",
    "model-b",
    conflict_index=index,
    exclude_conflicts=True,
)
self.assertEqual(logic["total"], 2)
```

Exercise the service response shapes without touching SQLite:

```python
@patch("app_core.dashboard_service.fetch_result_rows")
def test_overview_and_detail_report_raw_conflict_metadata(self, fetch_rows):
    rows = [
        result_row(1, "alice", "one.png", "model-a", user_id=10, logic="model-a"),
        result_row(2, "bob", "one.png", "model-b", user_id=20, logic="model-a"),
    ]
    fetch_rows.return_value = rows

    overview = dashboard_overview("T2I")
    pair = overview["pairs"][0]
    self.assertEqual(pair["dims"]["overall"]["conflict_sample_count"], 1)
    self.assertEqual(pair["dims"]["overall"]["sample_count"], 1)
    self.assertEqual(
        pair["scenes"][0]["dims"]["overall"]["conflict_sample_count"],
        1,
    )

    with patch(
        "app_core.dashboard_service.get_preview_prompt_text",
        return_value="prompt",
    ), patch("app_core.dashboard_service.get_ref_image_url", return_value=None):
        details = detail_results("T2I", "model-a", "model-b", "scene-1")

    self.assertEqual(len(details), 2)
    self.assertTrue(all(row["has_conflict"] for row in details))
    self.assertTrue(
        all(row["conflict_dimensions"] == ["overall"] for row in details)
    )
```

- [ ] **Step 2: Run conflict tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_conflicts tests.test_four_way_dashboard tests.test_video_dashboard
```

Expected: import errors for the conflict helpers and missing conflict metadata/annotations.

- [ ] **Step 3: Implement canonical evaluator/sample identity and conflict indexing**

Add these helpers above `dimension_stats`:

```python
def evaluator_identity(row):
    user_id = optional_row_value(row, "user_id")
    if user_id is not None:
        return ("user_id", user_id)
    return ("worker", optional_row_value(row, "worker"))


def sample_identity(row):
    v_a, v_b = sorted((row["v_a"], row["v_b"]))
    return (
        normalize_task_type(row["task_type"]),
        v_a,
        v_b,
        row["scene"],
        row["filename"],
    )


def build_conflict_index(rows, dimensions):
    vote_sides = {}
    for row in rows:
        sample_key = sample_identity(row)
        evaluator = evaluator_identity(row)
        canonical_a, canonical_b = sample_key[1], sample_key[2]
        for dimension in dimensions:
            value = optional_row_value(row, dimension)
            if value == canonical_a:
                side = "a"
            elif value == canonical_b:
                side = "b"
            else:
                continue
            sides = vote_sides.setdefault(
                (sample_key, dimension),
                {"a": set(), "b": set()},
            )
            sides[side].add(evaluator)

    conflicts = {}
    for (sample_key, dimension), sides in vote_sides.items():
        evaluators = sides["a"] | sides["b"]
        if sides["a"] and sides["b"] and len(evaluators) > 1:
            conflicts.setdefault(sample_key, set()).add(dimension)
    return conflicts
```

Do not compare literal labels such as `left`/`right`. Compare the stored winner to the canonical sorted model pair so legacy rows with reversed pair columns cannot invert the meaning of A/B.

- [ ] **Step 4: Extend dimension and pair/scene aggregation**

Replace `dimension_stats` with raw-metadata and optional-filter behavior:

```python
def dimension_stats(
    rows,
    dimension,
    v_a,
    v_b,
    *,
    conflict_index=None,
    exclude_conflicts=False,
):
    scored_rows = [
        row for row in rows
        if optional_row_value(row, dimension) is not None
    ]
    if conflict_index is None:
        conflict_index = build_conflict_index(scored_rows, [dimension])

    sample_keys = {sample_identity(row) for row in scored_rows}
    conflict_sample_keys = {
        key for key in sample_keys
        if dimension in conflict_index.get(key, set())
    }
    aggregate_rows = scored_rows
    if exclude_conflicts:
        aggregate_rows = [
            row for row in scored_rows
            if sample_identity(row) not in conflict_sample_keys
        ]

    tie_bad_count = sum(1 for row in aggregate_rows if row[dimension] == "tie_bad")
    tie_good_count = sum(1 for row in aggregate_rows if row[dimension] == "tie_good")
    return {
        "total": len(aggregate_rows),
        "v_a_wins": sum(1 for row in aggregate_rows if row[dimension] == v_a),
        "tie_bad_count": tie_bad_count,
        "tie_good_count": tie_good_count,
        "tie_count": tie_bad_count + tie_good_count,
        "v_b_wins": sum(1 for row in aggregate_rows if row[dimension] == v_b),
        "sample_count": len(sample_keys),
        "conflict_sample_count": len(conflict_sample_keys),
    }
```

Also make the two selector helpers tolerant of fixture/legacy mappings that lack a newly added score key:

```python
def rows_for_dimension(rows, dim):
    return [row for row in rows if optional_row_value(row, dim) is not None]


def active_dimensions(rows, configured):
    return [
        dimension
        for dimension in configured
        if any(optional_row_value(row, dimension) is not None for row in rows)
    ]
```

Extend pair aggregation:

```python
def aggregate_pair_rows(
    task_type: str,
    rows: Optional[list[sqlite3.Row]] = None,
    *,
    exclude_conflicts=False,
    conflict_index=None,
) -> List[dict]:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    dimensions = config["dashboard_dims"]
    rows = fetch_result_rows(task_type) if rows is None else list(rows)
    if conflict_index is None:
        conflict_index = build_conflict_index(rows, dimensions)

    grouped = {}
    for row in rows:
        grouped.setdefault((row["v_a"], row["v_b"]), []).append(row)

    result = []
    for (v_a, v_b), pair_rows in sorted(grouped.items()):
        pair_dimensions = active_dimensions(pair_rows, dimensions)
        pair_data = {
            "task_type": task_type,
            "pair": f"{v_a} vs {v_b}",
            "v_a": v_a,
            "v_b": v_b,
            "total": len(pair_rows),
            "active_dims": pair_dimensions,
            "dims": {},
            "bad_case": build_bad_case_stats(pair_rows),
            "scenes": [],
        }
        for dim in pair_dimensions:
            pair_data["dims"][dim] = dimension_stats(
                pair_rows,
                dim,
                v_a,
                v_b,
                conflict_index=conflict_index,
                exclude_conflicts=exclude_conflicts,
            )

        scene_grouped = {}
        for row in pair_rows:
            scene_grouped.setdefault(row["scene"], []).append(row)
        for scene_name, scene_rows in sorted(scene_grouped.items()):
            scene_dimensions = active_dimensions(scene_rows, dimensions)
            scene_data = {
                "scene": scene_name,
                "total": len(scene_rows),
                "active_dims": scene_dimensions,
                "dims": {},
                "bad_case": build_bad_case_stats(scene_rows),
            }
            for dim in scene_dimensions:
                scene_data["dims"][dim] = dimension_stats(
                    scene_rows,
                    dim,
                    v_a,
                    v_b,
                    conflict_index=conflict_index,
                    exclude_conflicts=exclude_conflicts,
                )
            pair_data["scenes"].append(scene_data)
        result.append(pair_data)
    return result
```

Update `dashboard_overview(task_type, exclude_conflicts=False)` to build the index once for all fetched rows and call:

```python
conflict_index = build_conflict_index(rows, config["dashboard_dims"])
pairs = aggregate_pair_rows(
    task_type,
    rows,
    exclude_conflicts=exclude_conflicts,
    conflict_index=conflict_index,
)
```

- [ ] **Step 5: Annotate every detail row**

Refactor the current detail list comprehension to a loop, build one index over the full detail query, and add:

```python
sample_key = sample_identity(row)
conflict_dimensions = sorted(
    conflict_index.get(sample_key, set()),
    key=lambda dimension: dimensions.index(dimension),
)

detail_item.update({
    "has_conflict": bool(conflict_dimensions),
    "conflict_dimensions": conflict_dimensions,
})
results.append(detail_item)
```

Use the task’s configured dashboard dimensions for deterministic label order. Return every row regardless of conflict state.

- [ ] **Step 6: Update exact legacy assertions, run tests, and commit**

Update full-dictionary expectations in `test_four_way_dashboard.py` to include:

```python
"sample_count": 5,
"conflict_sample_count": 0,
```

Ensure its fixtures include `task_type`, `scene`, `filename`, `worker`, and `user_id` so identity is meaningful.

Run:

```bash
python3 -m unittest tests.test_dashboard_conflicts tests.test_four_way_dashboard tests.test_video_dashboard
```

Expected: all tests pass.

Commit:

```bash
git add app_core/dashboard_service.py tests/test_dashboard_conflicts.py tests/test_four_way_dashboard.py tests/test_video_dashboard.py
git commit -m "feat: detect and report per-dimension evaluation conflicts"
```

---

## Task 4: Apply conflict exclusion consistently to services and API routes

**Files:**

- Modify: `/Users/baobinglei/code/ab_test/app_core/dashboard_service.py:114-146,266-295`
- Modify: `/Users/baobinglei/code/ab_test/main.py:272-284,342-344`
- Modify: `/Users/baobinglei/code/ab_test/tests/test_dashboard_conflicts.py`
- Create: `/Users/baobinglei/code/ab_test/tests/test_dashboard_conflict_routes.py`

- [ ] **Step 1: Add failing worker/ranking and route-forwarding tests**

For worker stats, make one conflicted sample and one clean sample and assert only the clean row contributes when filtering:

```python
rows = [
    result_row(1, "alice", "conflict.png", "model-a", user_id=1),
    result_row(2, "bob", "conflict.png", "model-b", user_id=2),
    result_row(3, "alice", "clean.png", "model-a", user_id=1),
]
with patch("app_core.dashboard_service.fetch_result_rows", return_value=rows):
    raw = worker_stats(
        "T2I", "model-a", "model-b", exclude_conflicts=False
    )
    filtered = worker_stats(
        "T2I", "model-a", "model-b", exclude_conflicts=True
    )
self.assertEqual(sum(item["overall"]["total"] for item in raw), 3)
self.assertEqual(sum(item["overall"]["total"] for item in filtered), 1)
```

For ranking, use the same dataset and dimension:

```python
with patch("app_core.dashboard_service.fetch_result_rows", return_value=rows):
    raw = ranking("T2I", dimension="overall", exclude_conflicts=False)
    filtered = ranking("T2I", dimension="overall", exclude_conflicts=True)
self.assertEqual({item["total"] for item in raw}, {3})
self.assertEqual({item["total"] for item in filtered}, {1})
```

Patch service callables in `main` and call the route functions directly:

```python
@patch("main.dashboard_overview_service", return_value={})
def test_overview_forwards_exclude_conflicts(self, service):
    main.dashboard_overview("T2I", exclude_conflicts=True)
    service.assert_called_once_with("T2I", exclude_conflicts=True)

@patch("main.worker_stats_service", return_value=[])
def test_worker_forwards_exclude_conflicts(self, service):
    main.worker_stats(
        "T2I", "model-a", "model-b", "scene-1", exclude_conflicts=True
    )
    service.assert_called_once_with(
        "T2I", "model-a", "model-b", "scene-1", exclude_conflicts=True
    )

@patch("main.ranking_service", return_value=[])
def test_ranking_forwards_exclude_conflicts(self, service):
    main.ranking("T2I", "scene-1", "overall", exclude_conflicts=True)
    service.assert_called_once_with(
        "T2I", "scene-1", "overall", exclude_conflicts=True
    )
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_conflicts tests.test_dashboard_conflict_routes
```

Expected: service and route signatures reject `exclude_conflicts`, and aggregate totals still include conflicts.

- [ ] **Step 3: Filter worker and ranking aggregates with the shared index**

Use one global conflict index before worker grouping:

```python
def worker_stats(
    task_type: str,
    v1: str,
    v2: str,
    scene: Optional[str] = None,
    exclude_conflicts: bool = False,
) -> list[dict]:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    v_a, v_b = sorted([v1, v2])
    rows = fetch_result_rows(task_type, v_a, v_b, scene)
    dimensions = config["dashboard_dims"]
    conflict_index = build_conflict_index(rows, dimensions)
    grouped = {}
    for row in rows:
        grouped.setdefault(row["worker"], []).append(row)

    result = []
    for worker, worker_rows in sorted(grouped.items()):
        active = active_dimensions(worker_rows, dimensions)
        entry = {
            "worker": worker,
            "total": len(worker_rows),
            "active_dims": active,
        }
        for dim in active:
            entry[dim] = dimension_stats(
                worker_rows,
                dim,
                v_a,
                v_b,
                conflict_index=conflict_index,
                exclude_conflicts=exclude_conflicts,
            )
        result.append(entry)
    return result
```

Use one index over all rows participating in ranking:

```python
def ranking(
    task_type: str = "T2I",
    scene: Optional[str] = None,
    dimension: str = "overall",
    exclude_conflicts: bool = False,
) -> list[dict]:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    if dimension not in config["dashboard_dims"]:
        raise InvalidDimensionError("无效维度")

    rows = rows_for_dimension(fetch_result_rows(task_type, scene=scene), dimension)
    conflict_index = build_conflict_index(rows, [dimension])
    if exclude_conflicts:
        rows = [
            row for row in rows
            if dimension not in conflict_index.get(sample_identity(row), set())
        ]

    stats = {}
    for row in rows:
        for model_name in (row["v_a"], row["v_b"]):
            stats.setdefault(model_name, {"wins": 0, "total": 0})
            stats[model_name]["total"] += 1
        if row[dimension] == row["v_a"]:
            stats[row["v_a"]]["wins"] += 1
        elif row[dimension] == row["v_b"]:
            stats[row["v_b"]]["wins"] += 1

    ranking_rows = []
    for model_name, entry in stats.items():
        total = entry["total"]
        ranking_rows.append({
            "model": model_name,
            "wins": entry["wins"],
            "total": total,
            "win_rate": round(entry["wins"] / total * 100, 1) if total else 0,
        })
    ranking_rows.sort(key=lambda item: item["win_rate"], reverse=True)
    return ranking_rows
```

- [ ] **Step 4: Expose optional query parameters**

```python
@app.get("/api/dashboard_overview")
def dashboard_overview(task_type: str, exclude_conflicts: bool = False):
    return dashboard_overview_service(
        task_type,
        exclude_conflicts=exclude_conflicts,
    )


@app.get("/api/worker_stats")
def worker_stats(
    task_type: str,
    v1: str,
    v2: str,
    scene: Optional[str] = None,
    exclude_conflicts: bool = False,
):
    return worker_stats_service(
        task_type, v1, v2, scene, exclude_conflicts=exclude_conflicts
    )


@app.get("/api/ranking")
def ranking(
    task_type: str = "T2I",
    scene: Optional[str] = None,
    dimension: str = "overall",
    exclude_conflicts: bool = False,
):
    return ranking_service(
        task_type, scene, dimension, exclude_conflicts=exclude_conflicts
    )
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 -m unittest tests.test_dashboard_conflicts tests.test_dashboard_conflict_routes
```

Expected: all tests pass.

Commit:

```bash
git add app_core/dashboard_service.py main.py tests/test_dashboard_conflicts.py tests/test_dashboard_conflict_routes.py
git commit -m "feat: support conflict-excluded dashboard aggregates"
```

---

## Task 5: Sort the complete detail dataset and add the conflict column

**Files:**

- Modify: `/Users/baobinglei/code/ab_test/templates/dashboard.html:1020-1033,1654-1685,2405-2573,3513-3528`
- Modify: `/Users/baobinglei/code/ab_test/tests/test_dashboard_detail_performance_ui.py`
- Modify: `/Users/baobinglei/code/ab_test/tests/test_video_dashboard_ui.py`

- [ ] **Step 1: Add failing pure-sort and markup tests**

Extract `sortDetailRows` into Node as the existing tests do for other JavaScript helpers. Assert all requested default directions and toggles against a deliberately shuffled full dataset:

```javascript
const assert = require('assert');
const rows = [
  { filename: 'b.png', worker: 'zoe', time: null, has_conflict: false, id: 4 },
  { filename: 'a.png', worker: 'bob', time: '2026-08-13T09:00:00+08:00', has_conflict: true, id: 2 },
  { filename: 'a.png', worker: 'amy', time: '2026-08-13T11:00:00+08:00', has_conflict: true, id: 1 },
  { filename: 'c.png', worker: 'amy', time: '2026-08-13T10:00:00+08:00', has_conflict: false, id: 3 },
];

assert.deepStrictEqual(
  sortDetailRows(rows, {key: 'filename', direction: 'asc'}).map(row => row.id),
  [1, 2, 4, 3],
);
assert.deepStrictEqual(
  sortDetailRows(rows, {key: 'worker', direction: 'asc'}).map(row => row.id),
  [1, 3, 2, 4],
);
assert.deepStrictEqual(
  sortDetailRows(rows, {key: 'time', direction: 'desc'}).map(row => row.id),
  [1, 3, 2, 4],
);
assert.deepStrictEqual(
  sortDetailRows(rows, {key: 'time', direction: 'asc'}).map(row => row.id),
  [2, 3, 1, 4],
);
assert.deepStrictEqual(
  sortDetailRows(rows, {key: 'conflict', direction: 'desc'}).map(row => row.id),
  [1, 2, 4, 3],
);
assert.deepStrictEqual(
  sortDetailRows(rows, {key: 'conflict', direction: 'asc'}).map(row => row.id),
  [4, 3, 1, 2],
);
```

Add source assertions that:

- sortable buttons exist for `filename`, `conflict`, `worker`, and `time`;
- conflict rows render `存在冲突` and use a red class;
- no-conflict rows render `无`;
- the empty-row `colspan` is 8;
- sorting appears before `paginateDetailRows` in `renderDetailTable`;
- detail rendering still contains no `<video>` construction.

- [ ] **Step 2: Run UI tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_detail_performance_ui tests.test_video_dashboard_ui
```

Expected: missing sort function/buttons/conflict column assertions fail.

- [ ] **Step 3: Add accessible header controls and state**

Replace the four relevant column labels with buttons and insert conflict after filename:

```html
<th>
  <button type="button" class="detail-sort-button" data-detail-sort-key="filename"
          onclick="setDetailSort('filename')">文件名 <span aria-hidden="true"></span></button>
</th>
<th>
  <button type="button" class="detail-sort-button" data-detail-sort-key="conflict"
          onclick="setDetailSort('conflict')">冲突提示 <span aria-hidden="true"></span></button>
</th>
<th>预览</th>
<th>Prompt</th>
<th>判定</th>
<th>坏例</th>
<th>
  <button type="button" class="detail-sort-button" data-detail-sort-key="worker"
          onclick="setDetailSort('worker')">评测员 <span aria-hidden="true"></span></button>
</th>
<th>
  <button type="button" class="detail-sort-button" data-detail-sort-key="time"
          onclick="setDetailSort('time')">评测时间 <span aria-hidden="true"></span></button>
</th>
```

Add state and defaults:

```javascript
const DETAIL_SORT_DEFAULTS = Object.freeze({
  filename: 'asc',
  conflict: 'desc',
  worker: 'asc',
  time: 'desc',
});

state.detailSort = { key: null, direction: null };
```

- [ ] **Step 4: Implement deterministic whole-result sorting**

Add a pure function that preserves missing times at the end and uses original order as final tie-breaker:

```javascript
function sortDetailRows(rows, sortState) {
  if (!sortState || !sortState.key) return rows.slice();
  const { key, direction } = sortState;
  const sign = direction === 'desc' ? -1 : 1;
  const compareText = (a, b) => String(a ?? '').localeCompare(String(b ?? ''), 'zh-CN');
  const compareTime = (a, b, timeDirection) => {
    const aMissing = !a;
    const bMissing = !b;
    if (aMissing || bMissing) {
      if (aMissing && bMissing) return 0;
      return aMissing ? 1 : -1;
    }
    const difference = Date.parse(a) - Date.parse(b);
    return timeDirection === 'desc' ? -difference : difference;
  };

  return rows.map((row, index) => ({ row, index })).sort((left, right) => {
    const a = left.row;
    const b = right.row;
    let compared = 0;
    if (key === 'time') {
      compared = compareTime(a.time, b.time, direction);
    } else if (key === 'conflict') {
      compared = (Number(Boolean(a.has_conflict)) - Number(Boolean(b.has_conflict))) * sign;
    } else {
      compared = compareText(a[key], b[key]) * sign;
    }
    if (!compared && key !== 'filename') compared = compareText(a.filename, b.filename);
    if (!compared && key !== 'worker') compared = compareText(a.worker, b.worker);
    if (!compared && key !== 'time') compared = compareTime(a.time, b.time, 'desc');
    return compared || (left.index - right.index);
  }).map(item => item.row);
}
```

Implement click/toggle behavior:

```javascript
function setDetailSort(key) {
  const current = state.detailSort;
  state.detailSort = current.key === key
    ? { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
    : { key, direction: DETAIL_SORT_DEFAULTS[key] };
  state.detailPage = 1;
  renderDetailTable();
}

function updateDetailSortHeaders() {
  document.querySelectorAll('[data-detail-sort-key]').forEach(button => {
    const active = button.dataset.detailSortKey === state.detailSort.key;
    const direction = active ? state.detailSort.direction : null;
    button.closest('th').setAttribute(
      'aria-sort',
      direction === 'asc' ? 'ascending' : direction === 'desc' ? 'descending' : 'none'
    );
    button.querySelector('span').textContent = direction === 'asc' ? '▲' : direction === 'desc' ? '▼' : '';
  });
}
```

Update `aria-sort` and arrow glyphs on every render. Reset and immediately clear the headers in `cleanupDetailModal`:

```javascript
state.detailSort = { key: null, direction: null };
updateDetailSortHeaders();
```

- [ ] **Step 5: Sort before paginating and render conflict cells**

Use this order in `renderDetailTable`:

```javascript
const filteredRows = state.detailRows.filter(row => {
  if (!state.selectedDetailWorkers.has(row.worker)) return false;
  if (fileFilter && !row.filename.toLowerCase().includes(fileFilter)) return false;
  if (resultFilter === 'a_win' && row.overall !== v1) return false;
  if (resultFilter === 'b_win' && row.overall !== v2) return false;
  if (resultFilter === 'tie_bad' && row.overall !== 'tie_bad') return false;
  if (resultFilter === 'tie_good' && row.overall !== 'tie_good') return false;
  return true;
});
const sortedRows = sortDetailRows(filteredRows, state.detailSort);
const pagination = paginateDetailRows(
  sortedRows,
  state.detailPage,
  DETAIL_PAGE_SIZE,
);
updateDetailSortHeaders();
```

Update the count and pagination visibility from `filteredRows.length`, but paginate only `sortedRows` and render only `pagination.items`.

Render the new cell:

```javascript
const conflictCell = createNode('td');
if (row.has_conflict) {
  conflictCell.className = 'detail-conflict-present';
  conflictCell.textContent = '存在冲突';
  conflictCell.title = (row.conflict_dimensions || [])
    .map(dimension => state.config.dashboard_dims
      .find(item => item.key === dimension)?.label || dimension)
    .join('、');
} else {
  conflictCell.textContent = '无';
}
tableRow.append(createCell(row.filename), conflictCell);
```

Style `.detail-conflict-present` with the existing danger red token or `#dc2626` and `font-weight: 700`. Change empty-state `colspan="8"`.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
python3 -m unittest tests.test_dashboard_detail_performance_ui tests.test_video_dashboard_ui
```

Expected: all tests pass, including Node sort probes.

Commit:

```bash
git add templates/dashboard.html tests/test_dashboard_detail_performance_ui.py tests/test_video_dashboard_ui.py
git commit -m "feat: sort dashboard details and highlight conflicts"
```

---

## Task 6: Display conflict reliability and refresh filtered statistics safely

**Files:**

- Modify: `/Users/baobinglei/code/ab_test/templates/dashboard.html:914-961,1654-1685,2121-2403,2595-2604,3513-3530`
- Create: `/Users/baobinglei/code/ab_test/tests/test_dashboard_conflict_ui.py`
- Modify: `/Users/baobinglei/code/ab_test/tests/test_dashboard_detail_performance_ui.py`

- [ ] **Step 1: Add failing checkbox, reliability, URL, and race tests**

Assert the source contains a default-unchecked filter in the task-control card:

```html
<input id="exclude-conflicts" type="checkbox" onchange="handleConflictFilterChange()">
```

Extract and run a small formatting helper in Node:

```javascript
assert.strictEqual(formatConflictReliability({
  conflict_sample_count: 1,
  sample_count: 4,
}), '冲突样例 1/4（25.0%）');

assert.strictEqual(formatConflictReliability({
  conflict_sample_count: 0,
  sample_count: 0,
}), '冲突样例 0/0（0.0%）');

assert.strictEqual(formatConflictReliability({total: 3}), null);
```

Add source/runtime assertions that overview, worker, and ranking URLs all include `exclude_conflicts`; the detail URL does not; and each aggregate loader checks a monotonically increasing request id before applying a response. Assert worker/ranking close paths increment their request ids.

Use exact function-source checks for the three guards:

```python
for function_name, request_key in (
    ("loadDashboard", "dashboardRequestId"),
    ("loadRanking", "rankingRequestId"),
    ("loadWorkerStats", "workerRequestId"),
):
    source = self.function_source(function_name)
    self.assertIn(f"const requestId = ++state.{request_key}", source)
    self.assertIn(f"requestId !== state.{request_key}", source)
    self.assertIn("exclude_conflicts", source)

detail_source = self.function_source("openDetailModal")
self.assertNotIn("exclude_conflicts", detail_source)
self.assertIn("state.rankingRequestId += 1", self.function_source("hideRanking"))
self.assertIn("state.workerRequestId += 1", self.function_source("closeModal"))
```

Run one out-of-order response probe against the extracted ranking loader:

```python
source = self.function_source("loadRanking")
result = self.run_node(f"""
{source}
(async () => {{
  const pending = [];
  const api = url => new Promise(resolve => pending.push({{ url, resolve }}));
  const state = {{
    taskType: 'T2I', excludeConflicts: true, rankingRequestId: 0
  }};
  const elements = {{
    'ranking-dimension': {{ value: 'overall' }},
    'ranking-scene': {{ value: 'scene-1' }},
    'ranking-card': {{ style: {{ display: 'block' }} }},
    'ranking-body': {{
      children: [],
      replaceChildren(...children) {{ this.children = children; }}
    }},
  }};
  const document = {{ getElementById: id => elements[id] }};
  const createNode = () => ({{
    cells: [], append(...cells) {{ this.cells = cells; }}
  }});
  const createCell = value => value;

  const first = loadRanking();
  const second = loadRanking();
  pending[1].resolve({{ json: async () => [{{
    model: 'new', wins: 1, total: 1, win_rate: 100
  }}] }});
  await second;
  pending[0].resolve({{ json: async () => [{{
    model: 'old', wins: 0, total: 1, win_rate: 0
  }}] }});
  await first;
  console.log(JSON.stringify({{
    urls: pending.map(item => item.url),
    model: elements['ranking-body'].children[0].cells[1],
  }}));
}})();
""")
self.assertEqual(result["model"], "new")
self.assertTrue(all("exclude_conflicts=true" in url for url in result["urls"]))
```

Also assert `renderWorkerStats` does not synthesize `sample_count` or `conflict_sample_count` before calling `renderSummaryBox`.

- [ ] **Step 2: Run UI tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_conflict_ui tests.test_dashboard_detail_performance_ui
```

Expected: missing filter, formatting, URL parameters, and stale-response guards.

- [ ] **Step 3: Add the filter control and reliability formatter**

Place the control in “任务控制与筛选”:

```html
<label class="filter-checkbox" for="exclude-conflicts">
  <input id="exclude-conflicts" type="checkbox" onchange="handleConflictFilterChange()">
  <span>统计时去除冲突项</span>
</label>
```

Add formatting/rendering helpers:

```javascript
function formatConflictReliability(stat) {
  if (stat?.sample_count === undefined || stat?.conflict_sample_count === undefined) {
    return null;
  }
  const total = Math.max(0, Number(stat.sample_count) || 0);
  const conflicts = Math.max(0, Number(stat.conflict_sample_count) || 0);
  const ratio = total ? (conflicts / total) * 100 : 0;
  return `冲突样例 ${conflicts}/${total}（${ratio.toFixed(1)}%）`;
}

function renderConflictReliability(stat) {
  const text = formatConflictReliability(stat);
  if (text === null) return null;
  const node = createNode('div', 'conflict-reliability');
  if (Number(stat.conflict_sample_count) > 0) node.classList.add('has-conflict');
  node.textContent = text;
  return node;
}
```

Append this node in pair-level `renderSummaryBox` and scene-level summaries only when non-null. Do not add it to worker rows or rankings. Style nonzero conflict text red; keep zero-conflict text muted.

Create the reliability node before the `!total` branch so exclusion of every conflicted vote still displays the raw reliability denominator:

```javascript
const reliability = renderConflictReliability(stat);
if (!total) {
  const legend = createNode('div', 'legend');
  legend.append(createNode('span', '', '暂无多维度样本'));
  box.append(legend);
  if (reliability) box.append(reliability);
  return box;
}

box.append(track, legend, renderSuppressionLine(stat));
if (reliability) box.append(reliability);
```

Use the same order in each scene dimension cell: build `reliability`, append the empty or populated vote visualization, then append `reliability` when it is non-null. The worker summary’s locally created `stat` remains limited to the six existing vote-count keys, so `renderSummaryBox` returns no reliability node there.

```css
.conflict-reliability {
  margin-top: 7px;
  color: var(--muted);
  font-size: 0.76rem;
}

.conflict-reliability.has-conflict {
  color: #dc2626;
  font-weight: 700;
}
```

- [ ] **Step 4: Add state and stale-response guards**

Extend state:

```javascript
excludeConflicts: false,
dashboardRequestId: 0,
rankingRequestId: 0,
workerRequestId: 0,
```

Use request IDs in all three aggregate loaders:

```javascript
async function loadDashboard() {
  const requestId = ++state.dashboardRequestId;
  const params = new URLSearchParams({
    task_type: state.taskType,
    exclude_conflicts: String(state.excludeConflicts),
  });
  const data = await api(`/api/dashboard_overview?${params}`).then(
    response => response.json()
  );
  if (requestId !== state.dashboardRequestId) return;
  state.overview = data;
  state.pairs = data.pairs.map(pair => ({
    ...pair,
    v_a_meta: catalogEntryFor(pair.v_a),
    v_b_meta: catalogEntryFor(pair.v_b),
  }));
  syncOverviewModelFilters();
  const rankingSceneSelect = document.getElementById('ranking-scene');
  const selectedRankingScene = rankingSceneSelect.value;
  const scenes = [...new Set(
    data.pairs.flatMap(pair => pair.scenes.map(scene => scene.scene))
  )];
  replaceSelectOptions(
    rankingSceneSelect,
    [['', '全部场景'], ...scenes.map(scene => [scene, scene])],
  );
  if (scenes.includes(selectedRankingScene)) {
    rankingSceneSelect.value = selectedRankingScene;
  }
  applyFilters();
  document.getElementById('status-tag').textContent =
    `最后更新: ${formatBeijingNow()}`;
}
```

Apply the same pattern to ranking:

```javascript
async function loadRanking() {
  const requestId = ++state.rankingRequestId;
  const params = new URLSearchParams({
    task_type: state.taskType,
    dimension: document.getElementById('ranking-dimension').value,
    exclude_conflicts: String(state.excludeConflicts),
  });
  const scene = document.getElementById('ranking-scene').value;
  if (scene) params.set('scene', scene);
  const rows = await api(`/api/ranking?${params}`).then(response => response.json());
  if (
    requestId !== state.rankingRequestId ||
    document.getElementById('ranking-card').style.display !== 'block'
  ) return;
  const body = document.getElementById('ranking-body');
  body.replaceChildren(...rows.map((row, index) => {
    const tableRow = createNode('tr');
    tableRow.append(
      createCell(index + 1),
      createCell(row.model),
      createCell(row.wins),
      createCell(row.total),
      createCell(`${row.win_rate}%`),
    );
    return tableRow;
  }));
}
```

The detail loader remains unchanged and never receives the filter parameter.

When closing worker/ranking UI, invalidate in-flight responses:

```javascript
function hideRanking() {
  state.rankingRequestId += 1;
  document.getElementById('ranking-card').style.display = 'none';
}
```

Change the ranking close button to `onclick="hideRanking()"`. Extend `closeModal` with:

```javascript
if (id === 'worker-modal') {
  state.workerRequestId += 1;
  state.workerRows = [];
  state.selectedWorkers = new Set();
  state.currentWorker = null;
}
```

- [ ] **Step 5: Refresh all currently visible aggregate views immediately**

```javascript
async function handleConflictFilterChange() {
  state.excludeConflicts = Boolean(
    document.getElementById('exclude-conflicts')?.checked
  );
  const refreshes = [loadDashboard()];
  if (document.getElementById('ranking-card').style.display === 'block') {
    refreshes.push(loadRanking());
  }
  if (
    document.getElementById('worker-modal').style.display === 'flex' &&
    state.currentWorker
  ) {
    refreshes.push(loadWorkerStats({ preserveSelection: true }));
  }
  await Promise.all(refreshes);
}
```

Refactor `openWorkerModal` to call this loader:

```javascript
async function loadWorkerStats({ preserveSelection = false } = {}) {
  const context = state.currentWorker;
  if (!context) return;
  const requestId = ++state.workerRequestId;
  const params = new URLSearchParams({
    task_type: state.taskType,
    v1: context.v1,
    v2: context.v2,
    exclude_conflicts: String(state.excludeConflicts),
  });
  if (context.scene) params.set('scene', context.scene);
  const rows = await api(`/api/worker_stats?${params}`).then(
    response => response.json()
  );
  if (
    requestId !== state.workerRequestId ||
    state.currentWorker !== context ||
    document.getElementById('worker-modal').style.display !== 'flex'
  ) return;

  const previous = new Set(state.selectedWorkers);
  state.workerRows = rows;
  const available = new Set(rows.map(row => row.worker));
  const preserved = new Set(
    [...previous].filter(worker => available.has(worker))
  );
  state.selectedWorkers = preserveSelection && preserved.size
    ? preserved
    : available;
  renderWorkerStats();
}

async function openWorkerModal(v1, v2, scene) {
  state.currentWorker = { v1, v2, scene };
  document.getElementById('worker-title').textContent = scene
    ? `评测员统计: ${v1} vs ${v2} [${scene}]`
    : `评测员统计: ${v1} vs ${v2} [全部场景]`;
  document.getElementById('worker-modal').style.display = 'flex';
  await loadWorkerStats({ preserveSelection: false });
}
```

When preserving selection, the intersection remains selected; reset to all returned workers only when that intersection is empty.

- [ ] **Step 6: Run UI tests and commit**

Run:

```bash
python3 -m unittest tests.test_dashboard_conflict_ui tests.test_dashboard_detail_performance_ui
```

Expected: all tests pass, including stale-response simulations.

Commit:

```bash
git add templates/dashboard.html tests/test_dashboard_conflict_ui.py tests/test_dashboard_detail_performance_ui.py
git commit -m "feat: add conflict reliability filter to dashboard"
```

---

## Task 7: Make evaluation HD preview fill the viewport

**Files:**

- Modify: `/Users/baobinglei/code/ab_test/templates/index.html` (evaluation lightbox CSS)
- Modify: `/Users/baobinglei/code/ab_test/tests/test_evaluation_preview_ui.py:62-95,1030-1158`

- [ ] **Step 1: Add a failing viewport geometry probe**

Extend the existing helper without breaking callers:

```python
def run_browser_style_probe(body, scenario, window_size=None):
    chrome = next((candidate for candidate in (
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ) if candidate and Path(candidate).exists()), None)
    if not chrome:
        self.skipTest("Chrome/Chromium is required for browser style coverage")
    style_start = self.html.index("<style>") + len("<style>")
    style_end = self.html.index("</style>", style_start)
    page = f'''<!doctype html><html><head><meta charset="utf-8">
<style>{self.html[style_start:style_end]}</style></head><body>{body}
<pre id="style-result"></pre><script>
document.getElementById("style-result").textContent = JSON.stringify((() => {{ {scenario} }})());
</script></body></html>'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "probe.html"
        path.write_text(page, encoding="utf-8")
        command = [
            chrome,
            "--headless=new",
            "--no-first-run",
            "--disable-background-networking",
            "--disable-gpu",
            "--no-sandbox",
        ]
        if window_size is not None:
            width, height = window_size
            command.append(f"--window-size={width},{height}")
        command.extend(["--dump-dom", path.as_uri()])
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    parser = StyleResultParser()
    parser.feed(result.stdout)
    parser.close()
    self.assertTrue(parser.value, result.stderr or result.stdout[-2000:])
    return json.loads(parser.value)
```

Add a browser test that opens the evaluation lightbox at `1440x900`, captures both viewport and dialog rectangles, and allows only the intended 12px inset:

```python
scenario = """
const dialog = document.querySelector('.lightbox-dialog').getBoundingClientRect();
return {
  viewportWidth: window.innerWidth,
  viewportHeight: window.innerHeight,
  left: dialog.left,
  top: dialog.top,
  right: dialog.right,
  bottom: dialog.bottom,
};
"""
probe = self.run_browser_style_probe(
    '<div class="lightbox open"><div class="lightbox-dialog"></div></div>',
    scenario,
    window_size=(1440, 900),
)
self.assertAlmostEqual(probe["left"], 12, delta=1)
self.assertAlmostEqual(probe["top"], 12, delta=1)
self.assertAlmostEqual(probe["viewportWidth"] - probe["right"], 12, delta=1)
self.assertAlmostEqual(probe["viewportHeight"] - probe["bottom"], 12, delta=1)
```

Skip only when the existing Chrome discovery helper cannot find a browser.

- [ ] **Step 2: Run the geometry test and confirm RED**

Run:

```bash
python3 -m unittest tests.test_evaluation_preview_ui
```

Expected: the geometry assertion reports the current width/height caps (`min(1700px, 100%)` and `min(92vh, 1020px)`) rather than a viewport-filling dialog.

- [ ] **Step 3: Match the dashboard full-screen overlay geometry**

Change only evaluation-lightbox geometry; preserve controls, content layout, and theme styles:

```css
.lightbox {
  padding: 12px;
}

.lightbox-dialog {
  width: 100%;
  height: calc(100vh - 24px);
  height: calc(100dvh - 24px);
  max-width: none;
  max-height: none;
}
```

Remove or override the old `width: min(1700px, 100%)` and `height: min(92vh, 1020px)` declarations. Keep `box-sizing: border-box` behavior intact.

- [ ] **Step 4: Run preview tests and commit**

Run:

```bash
python3 -m unittest tests.test_evaluation_preview_ui
```

Expected: all preview theme, interaction, and geometry tests pass.

Commit:

```bash
git add templates/index.html tests/test_evaluation_preview_ui.py
git commit -m "fix: fill viewport in evaluation HD preview"
```

---

## Task 8: Cross-feature regression and final verification

**Files:**

- Verify: `/Users/baobinglei/code/ab_test/app_core`
- Verify: `/Users/baobinglei/code/ab_test/templates`
- Verify: `/Users/baobinglei/code/ab_test/tests`
- Verify: `/Users/baobinglei/code/ab_test/README.md`

- [ ] **Step 1: Run all feature-focused tests together**

Run:

```bash
python3 -m unittest \
  tests.test_video_config_schema \
  tests.test_video_task_service \
  tests.test_video_evaluation_ui \
  tests.test_video_dashboard \
  tests.test_video_export \
  tests.test_dashboard_conflicts \
  tests.test_dashboard_conflict_routes \
  tests.test_four_way_dashboard \
  tests.test_dashboard_detail_performance_ui \
  tests.test_dashboard_conflict_ui \
  tests.test_video_dashboard_ui \
  tests.test_evaluation_preview_ui
```

Expected: all focused tests pass with no skips except an unavailable headless Chrome probe.

- [ ] **Step 2: Run JavaScript syntax validation for both templates**

Parse every inline script directly from each template without creating temporary files:

```bash
node -e 'const fs=require("fs"); for (const file of ["templates/index.html","templates/dashboard.html"]) { const html=fs.readFileSync(file,"utf8"); const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].map(match=>match[1]).filter(Boolean); scripts.forEach((source,index)=>{ try { new Function(source); } catch (error) { throw new Error(`${file} inline script ${index + 1}: ${error.message}`); } }); }'
```

Expected: the command exits 0.

- [ ] **Step 3: Run the complete regression suite**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: at least the baseline 443 tests plus the new tests pass.

- [ ] **Step 4: Inspect the final diff for contract consistency**

Run:

```bash
git diff --check
git status --short
git log --oneline -8
```

Verify explicitly:

- `structure_reasonableness` appears in configuration, schema, database migration, submit binding, evaluation payload, history, detail, export tests, and docs.
- overview, scene, worker, and ranking all use the same conflict identity/index semantics.
- conflict metadata denominators remain raw under exclusion.
- detail requests never pass `exclude_conflicts` and detail rows remain complete.
- sorting occurs before pagination.
- `database.db` remains untracked and untouched.
- no unfinished marker, placeholder, debug log, or temporary file was introduced.

- [ ] **Step 5: Commit only verification-driven fixes, if any**

If verification required code changes, rerun the smallest failing test first, then the full suite. Inspect `git diff --name-only`, stage each verified source/test path explicitly, never stage `database.db`, and create a narrowly scoped commit named `fix: address dashboard conflict regression`. If no fixes were required, do not create an empty commit.
