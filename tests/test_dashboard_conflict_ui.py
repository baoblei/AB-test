import json
import subprocess
import unittest
from pathlib import Path


class DashboardConflictUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/dashboard.html").read_text(encoding="utf-8")

    def function_source(self, name):
        marker = f"function {name}"
        if marker not in self.html:
            self.fail(f"missing JavaScript function {name}")
        start = self.html.index(marker)
        if self.html[max(0, start - 6) : start] == "async ":
            start -= 6
        brace = self.html.index("{", start)
        depth = 0
        for index in range(brace, len(self.html)):
            if self.html[index] == "{":
                depth += 1
            elif self.html[index] == "}":
                depth -= 1
                if depth == 0:
                    return self.html[start : index + 1]
        self.fail(f"function {name} is incomplete")

    def run_node(self, script):
        return json.loads(
            subprocess.check_output(["node", "-e", script], text=True)
        )

    def test_filter_is_default_unchecked_and_refreshes_on_change(self):
        self.assertIn(
            '<input id="exclude-conflicts" type="checkbox" onchange="handleConflictFilterChange()">',
            self.html,
        )
        self.assertNotIn('id="exclude-conflicts" type="checkbox" checked', self.html)
        source = self.function_source("handleConflictFilterChange")
        self.assertIn("state.excludeConflicts", source)
        self.assertIn("loadDashboard()", source)
        self.assertIn("loadRanking()", source)
        self.assertIn("loadWorkerStats({ preserveSelection: true })", source)
        self.assertIn("Promise.all(refreshes)", source)

    def test_conflict_tolerance_control_explains_boundary_and_shares_a_row_with_filter(self):
        self.assertIn('class="conflict-controls-row"', self.html)
        self.assertIn('id="conflict-tolerance"', self.html)
        self.assertIn('class="conflict-tolerance-label"', self.html)
        self.assertIn(
            ".input-group .conflict-tolerance-label {\n"
            "            color: #dc2626;",
            self.html,
        )
        self.assertIn('class="filter-checkbox conflict-exclude-checkbox"', self.html)
        self.assertIn(
            ".conflict-exclude-checkbox { align-self: flex-end; }", self.html
        )
        tolerance_section = self.html.split('id="conflict-tolerance"', 1)[1].split(
            "</select>", 1
        )[0]
        for percent in range(0, 51, 5):
            self.assertIn(f">{percent}%</option>", tolerance_section)
        for text in (
            "少数方",
            "严格大于宽容度",
            "0% 最严格",
            "50% 不判冲突",
            "一样好/一样差不参与",
        ):
            self.assertIn(text, self.html)

    def test_conflict_reliability_formatter_handles_zero_and_missing_metadata(self):
        source = self.function_source("formatConflictReliability")
        result = self.run_node(
            f"""
{source}
console.log(JSON.stringify([
  formatConflictReliability({{ conflict_sample_count: 1, sample_count: 4, intersection_sample_count: 2 }}),
  formatConflictReliability({{ conflict_sample_count: 0, sample_count: 0, intersection_sample_count: 0 }}),
  formatConflictReliability({{ total: 3 }}),
]));
"""
        )
        self.assertEqual(
            result,
            [
                "并集冲突比例 1/4（25.0%）\n交集冲突比例 1/2（50.0%）",
                "并集冲突比例 0/0（0.0%）\n交集冲突比例 0/0（0.0%）",
                None,
            ],
        )

    def test_pair_scene_and_worker_scope_render_reliable_conflict_counts(self):
        summary = self.function_source("renderSummaryBox")
        scene = self.function_source("renderSceneRow")
        worker = self.function_source("renderWorkerStats")
        self.assertIn("renderConflictReliability(stat)", summary)
        self.assertIn("renderConflictReliability(stat)", scene)
        self.assertIn("state.workerScope", worker)
        self.assertIn("scope.dims", worker)

    def test_aggregate_urls_include_filter_and_detail_url_does_not(self):
        for function_name, request_key in (
            ("loadDashboard", "dashboardRequestId"),
            ("loadRanking", "rankingRequestId"),
            ("loadWorkerStats", "workerRequestId"),
        ):
            source = self.function_source(function_name)
            self.assertIn(f"const requestId = ++state.{request_key}", source)
            self.assertIn(f"requestId !== state.{request_key}", source)
            self.assertIn("exclude_conflicts", source)
            self.assertIn("conflict_tolerance", source)

        detail_source = self.function_source("openDetailModal")
        self.assertNotIn("exclude_conflicts", detail_source)
        self.assertIn(
            "state.rankingRequestId += 1", self.function_source("hideRanking")
        )
        self.assertIn(
            "state.workerRequestId += 1", self.function_source("closeModal")
        )

    def test_detail_conflicts_recompute_from_selected_worker_scope_and_tolerance(self):
        source = self.function_source("recomputeDetailConflicts")
        result = self.run_node(
            f"""
{source}
const rows = [
  ...[1, 2, 3, 4].map(id => ({{
    filename: "one.png", worker: `majority-${{id}}`, evaluator_key: `user:${{id}}`,
    scores: {{ overall: "A" }}
  }})),
  {{ filename: "one.png", worker: "minority", evaluator_key: "user:5", scores: {{ overall: "B" }} }}
];
const dimensions = [{{ key: "overall" }}];
const workers = new Set(rows.map(row => row.worker));
const below = recomputeDetailConflicts(rows, dimensions, "A", "B", workers, 0.19);
const boundary = recomputeDetailConflicts(rows, dimensions, "A", "B", workers, 0.20);
const majorityOnly = recomputeDetailConflicts(
  rows, dimensions, "A", "B", new Set(["majority-1", "majority-2"]), 0
);
console.log(JSON.stringify({{
  below: below.every(row => row.has_conflict),
  boundary: boundary.some(row => row.has_conflict),
  majorityOnly: majorityOnly.some(row => row.has_conflict),
}}));
"""
        )
        self.assertEqual(
            result,
            {"below": True, "boundary": False, "majorityOnly": False},
        )

    def test_overview_uses_server_page_of_ten_and_exposes_navigation(self):
        for marker in (
            'id="overview-pagination"',
            'id="overview-page-prev"',
            'id="overview-page-status"',
            'id="overview-page-next"',
            "const OVERVIEW_PAGE_SIZE = 10",
            "function changeOverviewPage(",
        ):
            self.assertIn(marker, self.html)
        source = self.function_source("loadDashboard")
        for marker in (
            "page: String(state.overviewPage)",
            "page_size: String(OVERVIEW_PAGE_SIZE)",
            "search_v1",
            "search_v2",
            "scene",
            "model_names",
            "data.total_pages",
        ):
            self.assertIn(marker, source)

    def test_worker_refresh_preserves_the_available_selection(self):
        source = self.function_source("loadWorkerStats")
        for marker in (
            "const previous = new Set(state.selectedWorkers)",
            "const available = new Set(data.available_workers || [])",
            "[...previous].filter(worker => available.has(worker))",
            "preserveSelection ? preserved : available",
            'params.set("workers", JSON.stringify([...previous]))',
        ):
            self.assertIn(marker, source)

        result = self.run_node(
            f"""
const context = {{ v1: 'A', v2: 'B', scene: 'scene-1' }};
const state = {{
  taskType: 'T2I', excludeConflicts: true, conflictTolerance: 0.2,
  workerRequestId: 0, currentWorker: context,
  selectedWorkers: new Set(), workerRows: [], workerOptions: [], workerScope: null
}};
const document = {{
  getElementById: id => id === 'worker-modal'
    ? {{ style: {{ display: 'flex' }} }}
    : null
}};
const api = async () => ({{
  json: async () => ({{
    available_workers: ['alice', 'bob'], workers: [],
    scope: {{ total: 0, active_dims: [], dims: {{}} }}
  }})
}});
const renderWorkerStats = () => {{}};
{source}
(async () => {{
  await loadWorkerStats({{ preserveSelection: true }});
  console.log(JSON.stringify({{
    selected: [...state.selectedWorkers],
    rowCount: state.workerRows.length,
    options: state.workerOptions,
    scopeTotal: state.workerScope.total,
  }}));
}})();
"""
        )
        self.assertEqual(
            result,
            {"selected": [], "rowCount": 0, "options": ["alice", "bob"], "scopeTotal": 0},
        )

    def test_late_task_config_response_cannot_overwrite_new_task_type(self):
        source = self.function_source("handleTaskTypeChange")
        result = self.run_node(
            f"""
const elements = {{
  'task-type-select': {{ value: 'T2V' }},
  'dataset-download-task-type': {{ value: '' }},
  'overview-title': {{ textContent: '' }},
  'overview-desc': {{ textContent: '' }},
  'ranking-dimension': {{ value: '', options: [] }},
}};
const document = {{ getElementById: id => elements[id] }};
const state = {{
  taskType: 'T2I', config: null, taskConfigs: {{}},
  taskTypeRequestId: 0, dashboardRequestId: 0,
  rankingRequestId: 0, workerRequestId: 0,
}};
const pending = [];
const api = url => new Promise(resolve => pending.push({{ url, resolve }}));
const invalidateDatasetDownload = () => {{}};
const loadModelCatalog = async () => {{}};
const replaceSelectOptions = (element, options) => {{ element.options = options; }};
let dashboardLoads = 0;
const loadDashboard = async () => {{ dashboardLoads += 1; }};
const loadDatasets = async () => {{}};
{source}
(async () => {{
  const first = handleTaskTypeChange();
  elements['task-type-select'].value = 'TI2V';
  const second = handleTaskTypeChange();
  pending[1].resolve({{ json: async () => ({{
    task_type: 'TI2V', marker: 'new', media_type: 'video',
    dashboard_dims: [{{ key: 'image_consistency', label: '图像一致性' }}]
  }}) }});
  await second;
  pending[0].resolve({{ json: async () => ({{
    task_type: 'T2V', marker: 'old', media_type: 'video',
    dashboard_dims: [{{ key: 'overall', label: '整体' }}]
  }}) }});
  await first;
  console.log(JSON.stringify({{
    taskType: state.taskType,
    marker: state.config?.marker,
    cached: Object.keys(state.taskConfigs),
    dashboardLoads,
  }}));
}})();
"""
        )
        self.assertEqual(
            result,
            {
                "taskType": "TI2V",
                "marker": "new",
                "cached": ["TI2V"],
                "dashboardLoads": 1,
            },
        )

    def test_late_ranking_response_cannot_overwrite_newer_results(self):
        source = self.function_source("loadRanking")
        result = self.run_node(
            f"""
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
{source}
(async () => {{

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
"""
        )
        self.assertEqual(result["model"], "new")
        self.assertTrue(
            all("exclude_conflicts=true" in url for url in result["urls"])
        )


if __name__ == "__main__":
    unittest.main()
