# Four-Way Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace three-way judgments with four-way judgments across T2I and TI2I, center the TI2I reference image, show four-part result bars while merging both ties for suppression ratios, and clear only evaluation records.

**Architecture:** Keep the existing text result columns and model-name storage for A/B wins. Introduce two canonical tie values (`tie_bad`, `tie_good`), require an explicit overall judgment in full mode, aggregate both tie subtypes separately plus a combined `tie_count`, and update the existing server-rendered UI/export surfaces without a schema migration.

**Tech Stack:** Python 3, FastAPI/Pydantic, SQLite, `unittest`, `openpyxl`, server-rendered HTML/CSS, vanilla JavaScript, Node.js runtime probes.

## Global Constraints

- Apply the four choices to both T2I and TI2I, including overall-only evaluation.
- The exact UI order is `A 好 / 一样差 / 一样好 / B 好`, with shortcuts `1 / 2 / 3 / 4`.
- TI2I evaluation and evaluation lightbox order is candidate A / reference / candidate B; T2I remains candidate A / candidate B.
- Persist A/B wins as real model names and ties as exact values `tie_bad` and `tie_good`; never write ordinary `tie` after cleanup.
- Full evaluation requires an explicit overall choice plus every configured detail dimension.
- Suppression ratios use `tie_count = tie_bad_count + tie_good_count`; ranking wins exclude both ties.
- Do not change the database schema or add a dependency.
- Clear only `results_log` and `pair_tasks`; preserve users, operation logs, metadata, prompts, reference images, and result images.
- Preserve the user's existing uncommitted `.gitignore` and untracked `database.db`; never stage either file.

---

### Task 1: Enforce the four-way result contract in the task service

**Files:**
- Create: `app_core/result_choices.py`
- Modify: `app_core/database.py:96-101`
- Modify: `app_core/task_service.py:1-8,542-628,636-686`
- Modify: `app_core/bad_cases.py:1-50`
- Create: `tests/test_four_way_task_service.py`
- Modify: `tests/test_task_completion_atomicity.py`
- Modify: `tests/test_task_mode_integrity.py`
- Modify: `tests/test_business_time_writes.py`

**Interfaces:**
- Produces: `TIE_BAD = "tie_bad"`, `TIE_GOOD = "tie_good"`, `TIE_RESULTS`, and `resolve_vote_choice(choice, v_left, v_right) -> str`.
- Consumes: `VoteSubmit` optional string fields and the current task's randomized `v_left` / `v_right` model names.
- Guarantees: successful full rows contain explicit `overall` plus configured dimensions; T2I `fidelity` and every skipped result field are `NULL`.

- [ ] **Step 1: Write failing service tests for all four stored outcomes**

Create a temporary-database test fixture that inserts a fresh working task for each subtest and submits a complete T2I vote:

```python
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app_core.database import connect, init_db
from app_core.errors import AppError
from app_core.task_service import skip_task, submit_vote


class FourWayTaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch(
            "app_core.database.DB_PATH",
            str(Path(self.temp_dir.name) / "four-way.db"),
        )
        self.db_patch.start()
        init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def add_task(self, filename="sample.png"):
        conn = connect()
        task_id = conn.execute(
            """
            INSERT INTO pair_tasks
            (task_type, v_a, v_b, scene, filename, status, eval_mode, worker, assigned_user_id)
            VALUES ('T2I', 'model-a', 'model-b', 'scene', ?, 'working', 'full', 'worker', 1)
            """,
            (filename,),
        ).lastrowid
        conn.commit()
        conn.close()
        return task_id

    def vote(self, task_id, **overrides):
        payload = dict(
            task_type="T2I", eval_mode="full", task_id=task_id,
            v_left="model-b", v_right="model-a", scene="scene",
            filename="sample.png", worker="ignored", overall="tie_good",
            aesthetic="left", logic="tie_bad", consistency="right",
            fidelity=None, bad_case_left=[], bad_case_right=[], duration_seconds=3,
        )
        payload.update(overrides)
        return SimpleNamespace(**payload)

    def test_submit_maps_sides_and_preserves_both_tie_subtypes(self):
        task_id = self.add_task()
        self.assertEqual(submit_vote(self.vote(task_id), 1, "worker"), {"status": "ok"})
        conn = connect()
        row = conn.execute(
            "SELECT overall, aesthetic, logic, consistency, fidelity FROM results_log WHERE task_id=?",
            (task_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row, ("tie_good", "model-b", "tie_bad", "model-a", None))
```

- [ ] **Step 2: Write failing tests for explicit overall, invalid choices, and skipped NULLs**

Add these methods to the same class:

```python
    def task_status(self, task_id):
        conn = connect()
        value = conn.execute("SELECT status FROM pair_tasks WHERE id=?", (task_id,)).fetchone()[0]
        conn.close()
        return value

    def test_full_vote_requires_explicit_overall(self):
        task_id = self.add_task()
        with self.assertRaisesRegex(AppError, "请完成所有评分维度"):
            submit_vote(self.vote(task_id, overall=None), 1, "worker")
        self.assertEqual(self.task_status(task_id), "working")

    def test_unknown_choice_is_rejected_instead_of_becoming_tie(self):
        task_id = self.add_task()
        with self.assertRaisesRegex(AppError, "无效评测选项"):
            submit_vote(self.vote(task_id, logic="tie"), 1, "worker")
        self.assertEqual(self.task_status(task_id), "working")

    def test_skip_stores_no_result_placeholders(self):
        task_id = self.add_task()
        self.assertEqual(skip_task(task_id, "T2I", 1), {"status": "ok"})
        conn = connect()
        row = conn.execute(
            "SELECT overall, aesthetic, logic, consistency, fidelity, skipped FROM results_log WHERE task_id=?",
            (task_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row, (None, None, None, None, None, 1))
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_four_way_task_service -v
```

Expected: failures show that full mode derives overall, unknown values become `tie`, T2I fidelity becomes `tie`, and skipped rows contain `skipped` placeholders.

- [ ] **Step 4: Add canonical result constants and strict resolution**

Create `app_core/result_choices.py`:

```python
from typing import Optional

from .errors import AppError

TIE_BAD = "tie_bad"
TIE_GOOD = "tie_good"
TIE_RESULTS = (TIE_BAD, TIE_GOOD)


def resolve_vote_choice(choice: Optional[str], v_left: str, v_right: str) -> str:
    if choice == "left":
        return v_left
    if choice == "right":
        return v_right
    if choice in TIE_RESULTS:
        return choice
    raise AppError("无效评测选项")
```

- [ ] **Step 5: Make full overall explicit and stop writing placeholder result values**

In `submit_vote()`, replace the permissive resolver and derived overall path with:

```python
    if eval_mode == "overall":
        overall = resolve_vote_choice(vote.overall, vote.v_left, vote.v_right)
        dim_values = {"aesthetic": None, "logic": None, "consistency": None, "fidelity": None}
    else:
        required_dims = ["overall", *config["eval_dims"]]
        missing_dims = [dim for dim in required_dims if not getattr(vote, dim, None)]
        if missing_dims:
            raise AppError("请完成所有评分维度")
        overall = resolve_vote_choice(vote.overall, vote.v_left, vote.v_right)
        dim_values = {
            "aesthetic": resolve_vote_choice(vote.aesthetic, vote.v_left, vote.v_right),
            "logic": resolve_vote_choice(vote.logic, vote.v_left, vote.v_right),
            "consistency": resolve_vote_choice(vote.consistency, vote.v_left, vote.v_right),
            "fidelity": (
                resolve_vote_choice(vote.fidelity, vote.v_left, vote.v_right)
                if "fidelity" in config["eval_dims"] else None
            ),
        }
```

Import `resolve_vote_choice` from `result_choices`, remove the `derive_overall_result` import and now-unused function, and change the legacy fidelity column fallback to `ensure_column(cursor, "results_log", "fidelity", "TEXT")`.

Change the skipped insert to use bound NULL result fields:

```python
cursor.execute(
    """
    INSERT INTO results_log (
        task_id, eval_mode, task_type, v_a, v_b, scene, filename,
        overall, aesthetic, logic, consistency, fidelity,
        worker, timestamp, skipped, user_id,
        bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, '[]', '[]', '[]', '[]')
    """,
    (
        task_id, eval_mode, task_type, task[0], task[1], task[2], task[3],
        None, None, None, None, None,
        authenticated_worker, now_beijing_iso(), user_id,
    ),
)
```

- [ ] **Step 6: Update existing service fixtures to the new valid contract**

For existing successful full votes, set `overall` to a real four-way value and replace ordinary `tie` detail choices with `tie_bad` or `tie_good`. Keep tests that intentionally omit overall only when they assert the new validation error. Change assertions for skipped result columns from `"skipped"` to `None`.

- [ ] **Step 7: Verify GREEN and service regressions**

Run:

```bash
python3 -m unittest tests.test_four_way_task_service tests.test_task_completion_atomicity tests.test_task_mode_integrity tests.test_business_time_writes -v
```

Expected: all tests PASS and successful rows contain no ordinary `tie` or `skipped` result placeholder.

- [ ] **Step 8: Commit the result contract**

```bash
git add app_core/result_choices.py app_core/database.py app_core/task_service.py app_core/bad_cases.py tests/test_four_way_task_service.py tests/test_task_completion_atomicity.py tests/test_task_mode_integrity.py tests/test_business_time_writes.py
git commit -m "feat: enforce four-way evaluation results"
```

---

### Task 2: Render four choices and center the TI2I reference image

**Files:**
- Modify: `templates/index.html:923-947,1200-1205,1368-1389,1544-1565,1888-1910,2545-2565`
- Modify: `tests/test_evaluation_shortcuts_ui.py`
- Modify: `tests/test_evaluation_preview_ui.py`
- Modify: `tests/test_frontend_time_contract.py:65`
- Create: `tests/test_four_way_evaluation_ui.py`

**Interfaces:**
- Consumes: `state.config.eval_dims`, `state.config.show_ref`, and current task image URLs.
- Produces: `getActiveEvalDims()` with explicit `overall` in full mode; radio IDs ending in `left`, `tie_bad`, `tie_good`, `right`; main/lightbox pane order `left`, `reference`, `right` for TI2I.

- [ ] **Step 1: Write failing markup and dimension tests**

Create `tests/test_four_way_evaluation_ui.py`:

```python
import unittest
from pathlib import Path


class FourWayEvaluationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/index.html").read_text(encoding="utf-8")

    def function_source(self, name, next_name):
        start = self.html.index(f"function {name}")
        return self.html[start:self.html.index(f"function {next_name}", start)]

    def test_full_mode_includes_explicit_overall_dimension(self):
        source = self.function_source("getActiveEvalDims", "handleEvalModeChange")
        self.assertIn('[{ key: "overall", label: "整体" }, ...state.config.eval_dims]', source)

    def test_evaluation_table_has_four_ordered_choices(self):
        source = self.function_source("renderEvalTable", "previewToolIcon")
        for value in ("left", "tie_bad", "tie_good", "right"):
            self.assertIn(value, source)
        positions = [source.index(label) for label in ("A 好", "一样差", "一样好", "B 好")]
        self.assertEqual(positions, sorted(positions))

    def test_ti2i_main_and_lightbox_put_reference_between_candidates(self):
        main = self.function_source("renderCompareGrid", "renderImageCard")
        lightbox = self.function_source("renderLightbox", "renderLightboxPane")
        self.assertLess(main.index('renderImageCard("left"'), main.index('renderImageCard("reference"')))
        self.assertLess(main.index('renderImageCard("reference"'), main.index('renderImageCard("right"')))
        self.assertLess(lightbox.index('side: "left"'), lightbox.index('side: "reference"'))
        self.assertLess(lightbox.index('side: "reference"'), lightbox.index('side: "right"'))
```

- [ ] **Step 2: Extend the shortcut test to require keys 1–4**

Change the mapping to:

```python
for key, choice in (("1", "left"), ("2", "tie_bad"), ("3", "tie_good"), ("4", "right")):
    with self.subTest(key=key):
        result = self.run_shortcut(selected={"overall": "left"}, key=key)
        self.assertEqual(result["clicked"], [f"opt-aesthetic-{choice}"])
```

Use `{"overall": "left", "aesthetic": "tie_bad", "logic": "right"}` for the all-selected fixture.

- [ ] **Step 3: Run the UI tests and verify RED**

```bash
python3 -m unittest tests.test_four_way_evaluation_ui tests.test_evaluation_shortcuts_ui -v
```

Expected: failures show only three choices/shortcuts, no explicit overall in full mode, and reference-first TI2I ordering.

- [ ] **Step 4: Implement the four-choice table and explicit overall row**

Change `getActiveEvalDims()` to:

```javascript
function getActiveEvalDims() {
    return state.overallOnly
        ? [{ key: "overall", label: "整体" }]
        : [{ key: "overall", label: "整体" }, ...state.config.eval_dims];
}
```

Render complete radio cells from:

```javascript
const choices = [
    ["left", "A 好"],
    ["tie_bad", "一样差"],
    ["tie_good", "一样好"],
    ["right", "B 好"]
];

body.innerHTML = dims.map(item => `
    <tr>
        <td class="dim-name">${item.label}</td>
        ${choices.map(([value, label]) => `
            <td class="radio-cell">
                <input type="radio" name="${item.key}" id="opt-${item.key}-${value}"
                       onchange="handleVote('${item.key}', '${value}')">
                <label class="radio-label" for="opt-${item.key}-${value}">
                    <span class="radio-dot"></span><span>${label}</span>
                </label>
            </td>
        `).join("")}
    </tr>
`).join("");
```

Update the static header and help copy to four columns and `1 / 2 / 3 / 4 / Enter`. Change the `tests/test_frontend_time_contract.py` runtime fixture from `overall: "tie"` to `overall: "tie_good"` so all active frontend fixtures follow the production contract.

- [ ] **Step 5: Reorder evaluation panes without changing T2I**

Build both main and lightbox arrays as left, conditional reference, right:

```javascript
cards.push(renderImageCard("left", "候选图 A", task.left_img, true));
panes.push({ id: "left", label: "候选图 A" });
if (state.config.show_ref) {
    cards.push(renderImageCard("reference", "参考图", task.ref_img, true));
    panes.push({ id: "reference", label: "参考图" });
}
cards.push(renderImageCard("right", "候选图 B", task.right_img, true));
panes.push({ id: "right", label: "候选图 B" });
```

Keep `buildHoldComparePairs()` unchanged so it consumes the corrected pane order.

- [ ] **Step 6: Implement shortcuts 1–4**

```javascript
const shortcutChoice = event.key === "1" ? "left"
    : event.key === "2" ? "tie_bad"
    : event.key === "3" ? "tie_good"
    : event.key === "4" ? "right"
    : null;
```

- [ ] **Step 7: Verify GREEN and evaluation-preview regressions**

```bash
python3 -m unittest tests.test_four_way_evaluation_ui tests.test_evaluation_shortcuts_ui tests.test_evaluation_preview_ui -v
```

Expected: all tests PASS; zoom, sync, compare, prompt, loading, and responsive behavior remains green.

- [ ] **Step 8: Commit the evaluation UI**

```bash
git add templates/index.html tests/test_four_way_evaluation_ui.py tests/test_evaluation_shortcuts_ui.py tests/test_evaluation_preview_ui.py tests/test_frontend_time_contract.py
git commit -m "feat: add four-way evaluation controls"
```

---

### Task 3: Aggregate and render four-part dashboard results

**Files:**
- Modify: `app_core/dashboard_service.py:1-48`
- Modify: `templates/dashboard.html:13-24,170-184,2028-2152,2308-2410,2440-2490`
- Create: `tests/test_four_way_dashboard.py`
- Modify: `tests/test_dashboard_export_ui.py`
- Modify: `tests/test_dashboard_detail_performance_ui.py`

**Interfaces:**
- Consumes: stored values equal to model A, `tie_bad`, `tie_good`, or model B.
- Produces: every dimension stat has `total`, `v_a_wins`, `tie_bad_count`, `tie_good_count`, `tie_count`, and `v_b_wins`.
- Dashboard `renderSuppressionLine(stat)` continues to consume combined `tie_count` only.

- [ ] **Step 1: Write failing aggregation tests**

Create `tests/test_four_way_dashboard.py`:

```python
import unittest
from app_core.dashboard_service import dimension_stats


class FourWayDashboardTests(unittest.TestCase):
    def test_dimension_stats_separates_ties_and_keeps_combined_count(self):
        rows = [
            {"eval_mode": "full", "overall": "A"},
            {"eval_mode": "full", "overall": "tie_bad"},
            {"eval_mode": "full", "overall": "tie_good"},
            {"eval_mode": "full", "overall": "B"},
            {"eval_mode": "full", "overall": "tie_good"},
        ]
        self.assertEqual(
            dimension_stats(rows, "overall", "A", "B"),
            {"total": 5, "v_a_wins": 1, "tie_bad_count": 1,
             "tie_good_count": 2, "tie_count": 3, "v_b_wins": 1},
        )
```

- [ ] **Step 2: Write a failing Node probe for four bar segments and merged suppression**

In `tests/test_dashboard_export_ui.py`, execute `renderSummaryBox()` with stat `{total: 8, v_a_wins: 2, tie_bad_count: 1, tie_good_count: 3, tie_count: 4, v_b_wins: 2}` and a fake `createNode()`. Assert:

```python
self.assertEqual(result["segments"], [
    ["seg-a", "25.0%"],
    ["seg-tie-bad", "12.5%"],
    ["seg-tie-good", "37.5%"],
    ["seg-b", "25.0%"],
])
self.assertIn("A压制 1.00 (6/6)", result["text"])
self.assertIn("B压制 1.00 (6/6)", result["text"])
```

Also assert `renderSceneRow()` and `renderWorkerStats()` mention both subtype fields.

- [ ] **Step 3: Run dashboard tests and verify RED**

```bash
python3 -m unittest tests.test_four_way_dashboard tests.test_dashboard_export_ui -v
```

Expected: aggregation lacks subtype counts and the bar has only A / tie / B.

- [ ] **Step 4: Return separate and combined tie counts**

```python
def dimension_stats(rows, dim: str, v_a: str, v_b: str) -> dict:
    scoped_rows = rows_for_dimension(rows, dim)
    tie_bad_count = sum(1 for row in scoped_rows if row[dim] == "tie_bad")
    tie_good_count = sum(1 for row in scoped_rows if row[dim] == "tie_good")
    return {
        "total": len(scoped_rows),
        "v_a_wins": sum(1 for row in scoped_rows if row[dim] == v_a),
        "tie_bad_count": tie_bad_count,
        "tie_good_count": tie_good_count,
        "tie_count": tie_bad_count + tie_good_count,
        "v_b_wins": sum(1 for row in scoped_rows if row[dim] == v_b),
    }
```

- [ ] **Step 5: Render four colors, percentages, and labels**

Add distinct `--tie-bad` and `--tie-good` colors plus matching segment/badge classes. In summary and scene renderers calculate:

```javascript
const tieBadPct = (stat.tie_bad_count / total * 100).toFixed(1);
const tieGoodPct = (stat.tie_good_count / total * 100).toFixed(1);
```

Render tuples in order:

```javascript
[["seg-a", aPct], ["seg-tie-bad", tieBadPct],
 ["seg-tie-good", tieGoodPct], ["seg-b", bPct]]
```

Use labels `A`, `一样差`, `一样好`, `B`. Keep `renderSuppressionLine()` unchanged because it already uses combined `stat.tie_count`.

- [ ] **Step 6: Update worker summaries and detail filters/badges**

Worker reductions sum subtype fields and combined tie:

```javascript
tie_bad_count: rows.reduce((sum, row) => sum + row[dim.key].tie_bad_count, 0),
tie_good_count: rows.reduce((sum, row) => sum + row[dim.key].tie_good_count, 0),
tie_count: rows.reduce((sum, row) => sum + row[dim.key].tie_count, 0),
```

Worker cells display `A n / 一样差 n / 一样好 n / B n`. Replace the detail filter's single tie option with `tie_bad` and `tie_good`, filter exact values, and map both in `renderResultRow()` to Chinese labels and distinct badges.

- [ ] **Step 7: Verify GREEN and dashboard regressions**

```bash
python3 -m unittest tests.test_four_way_dashboard tests.test_dashboard_export_ui tests.test_dashboard_detail_performance_ui tests.test_dashboard_image_preview_ui tests.test_dashboard_model_hierarchy_ui -v
```

Expected: all tests PASS and summary/scene bars both expose four segments.

- [ ] **Step 8: Commit dashboard statistics and rendering**

```bash
git add app_core/dashboard_service.py templates/dashboard.html tests/test_four_way_dashboard.py tests/test_dashboard_export_ui.py tests/test_dashboard_detail_performance_ui.py
git commit -m "feat: show four-way dashboard results"
```

---

### Task 4: Update export, profile, filters, and documentation

**Files:**
- Modify: `app_core/export_service.py:28-31,72-122,208-235,309-345`
- Modify: `templates/dashboard.html:1058-1068`
- Modify: `templates/profile.html:125-140,334-348`
- Modify: `tests/test_export_filtering.py`
- Modify: `tests/test_export_workbook.py`
- Modify: `tests/test_dashboard_export_ui.py`
- Create: `tests/test_four_way_profile_ui.py`
- Modify: `README.md:18-24,286-294,391-423`

**Interfaces:**
- Produces: filters `all`, `a`, `tie_bad`, `tie_good`, `b`; summary subtype counts/rates; combined ties only for suppression.
- Consumes: `ExportRequest.result_filter`, workbook rows, and profile history `overall` values.

- [ ] **Step 1: Write failing export filter and summary tests**

Update row factories to use `tie_good` as their neutral default, then add:

```python
def test_tie_subtype_filters_are_independent(self):
    rows = [make_row(1, overall="tie_bad"), make_row(2, overall="tie_good"), make_row(3, overall="A")]
    for result_filter, expected_ids in (("tie_bad", [1]), ("tie_good", [2])):
        with self.subTest(result_filter=result_filter):
            request = ExportRequest(task_type="T2I", v1="A", v2="B", result_filter=result_filter)
            self.assertEqual(
                [row["id"] for row in filter_rows(rows, request, "overall")],
                expected_ids,
            )
```

Add a workbook summary test with A, `tie_bad`, two `tie_good`, and B rows. Assert separate count/rate columns and suppression `(1 + 3) / (1 + 3) == 1`.

- [ ] **Step 2: Write failing profile-label and selector tests**

Create `tests/test_four_way_profile_ui.py`:

```python
import unittest
from pathlib import Path


class FourWayProfileUiTests(unittest.TestCase):
    def test_profile_maps_both_tie_subtypes_without_generic_tie(self):
        html = Path("templates/profile.html").read_text(encoding="utf-8")
        self.assertIn("r.overall === 'tie_bad'", html)
        self.assertIn("一样差", html)
        self.assertIn("r.overall === 'tie_good'", html)
        self.assertIn("一样好", html)
        self.assertNotIn("r.overall === 'tie'", html)
```

Extend dashboard export UI assertions so the select contains `tie_bad`, `tie_good` and no `<option value="tie">`.

- [ ] **Step 3: Run export/profile tests and verify RED**

```bash
python3 -m unittest tests.test_export_filtering tests.test_export_workbook tests.test_four_way_profile_ui tests.test_dashboard_export_ui -v
```

Expected: subtype filters are rejected, summaries have one tie column, and profile/selectors still display generic tie.

- [ ] **Step 4: Split export filtering and summaries**

```python
VALID_RESULT_FILTERS = {"all", "a", "tie_bad", "tie_good", "b"}


def expected_result(request, v_a=None, v_b=None):
    if v_a is None or v_b is None:
        v_a, v_b = canonical_models(request)
    return {"all": None, "a": v_a, "tie_bad": "tie_bad",
            "tie_good": "tie_good", "b": v_b}[request.result_filter]
```

In `summarize_overall()`, count both subtypes separately, set `ties = tie_bad + tie_good`, expose both rates, and continue using `ties` in suppression. Change summary columns to:

```text
场景, 总数, A胜数, A胜率, 一样差数, 一样差率,
一样好数, 一样好率, B胜数, B胜率, A抑制比, B抑制比,
A坏例数, A坏例率, B坏例数, B坏例率
```

Apply percent formats to columns `4, 6, 8, 10, 14, 16`. In detail cells map `tie_bad` to `一样差` and `tie_good` to `一样好`; leave real model names unchanged.

- [ ] **Step 5: Update selectors, profile badges, and README**

Use exact filter options:

```html
<option value="all">全部</option>
<option value="a">A 胜</option>
<option value="tie_bad">一样差</option>
<option value="tie_good">一样好</option>
<option value="b">B 胜</option>
```

Profile history maps both tie values to separate badges. Update README evaluation instructions, dashboard description, filter list, and workbook summary description; state that suppression combines both tie subtypes.

- [ ] **Step 6: Verify GREEN and export/archive regressions**

```bash
python3 -m unittest tests.test_export_filtering tests.test_export_workbook tests.test_export_archive tests.test_dashboard_export_ui tests.test_four_way_profile_ui -v
```

Expected: all tests PASS; workbooks have separate “一样差/一样好” columns and no generic tie output.

- [ ] **Step 7: Commit secondary surfaces and docs**

```bash
git add app_core/export_service.py templates/dashboard.html templates/profile.html tests/test_export_filtering.py tests/test_export_workbook.py tests/test_dashboard_export_ui.py tests/test_four_way_profile_ui.py README.md
git commit -m "feat: expose four-way results across exports"
```

---

### Task 5: Run complete verification and clear evaluation records

**Files:**
- Modify data only: `database.db` tables `results_log`, `pair_tasks`
- Verify: all source and test files changed in Tasks 1–4

**Interfaces:**
- Consumes: the finalized four-way implementation and configured local SQLite database.
- Produces: a verified application and empty evaluation/task tables while retaining user and operation-log rows.

- [ ] **Step 1: Record pre-cleanup table counts**

```bash
sqlite3 database.db "SELECT 'results_log', COUNT(*) FROM results_log UNION ALL SELECT 'pair_tasks', COUNT(*) FROM pair_tasks UNION ALL SELECT 'users', COUNT(*) FROM users UNION ALL SELECT 'operation_logs', COUNT(*) FROM operation_logs;"
```

Expected: four named counts. Record `users` and `operation_logs` for comparison after cleanup.

- [ ] **Step 2: Run the full automated suite before destructive cleanup**

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests PASS with zero failures and zero errors.

- [ ] **Step 3: Run compile and whitespace verification**

```bash
python3 -m compileall -q app_core main.py tests
git diff --check
```

Expected: both commands exit 0 with no output.

- [ ] **Step 4: Audit source paths for forbidden ordinary tie writes**

```bash
rg -n 'return "tie"|= "tie"|VALUES[^;]*tie|value="tie"|overall === .tie.' app_core templates --glob '*.py' --glob '*.html'
```

Expected: no matches. Mentions in design/plan documents and historical commits are out of scope.

- [ ] **Step 5: Clear only evaluation data in one transaction**

```bash
sqlite3 -bail database.db "BEGIN IMMEDIATE; DELETE FROM results_log; DELETE FROM pair_tasks; COMMIT;"
```

Expected: exit 0. This deletion is authorized by the approved design; do not delete or recreate `database.db`.

- [ ] **Step 6: Verify the destructive action's exact scope**

```bash
sqlite3 database.db "SELECT 'results_log', COUNT(*) FROM results_log UNION ALL SELECT 'pair_tasks', COUNT(*) FROM pair_tasks UNION ALL SELECT 'users', COUNT(*) FROM users UNION ALL SELECT 'operation_logs', COUNT(*) FROM operation_logs;"
```

Expected: `results_log|0` and `pair_tasks|0`; `users` and `operation_logs` equal Step 1.

- [ ] **Step 7: Inspect final repository state without staging user files**

```bash
git status --short
git log -5 --oneline --decorate
```

Expected: `.gitignore` remains the user's unstaged modification, `database.db` remains untracked, feature commits are present, and no implementation file is left unstaged.
