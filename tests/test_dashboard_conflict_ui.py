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

    def test_conflict_reliability_formatter_handles_zero_and_missing_metadata(self):
        source = self.function_source("formatConflictReliability")
        result = self.run_node(
            f"""
{source}
console.log(JSON.stringify([
  formatConflictReliability({{ conflict_sample_count: 1, sample_count: 4 }}),
  formatConflictReliability({{ conflict_sample_count: 0, sample_count: 0 }}),
  formatConflictReliability({{ total: 3 }}),
]));
"""
        )
        self.assertEqual(
            result,
            ["冲突样例 1/4（25.0%）", "冲突样例 0/0（0.0%）", None],
        )

    def test_pair_and_scene_render_reliability_but_worker_summary_does_not_fabricate_it(self):
        summary = self.function_source("renderSummaryBox")
        scene = self.function_source("renderSceneRow")
        worker = self.function_source("renderWorkerStats")
        self.assertIn("renderConflictReliability(stat)", summary)
        self.assertIn("renderConflictReliability(stat)", scene)
        self.assertNotIn("sample_count:", worker)
        self.assertNotIn("conflict_sample_count:", worker)

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

        detail_source = self.function_source("openDetailModal")
        self.assertNotIn("exclude_conflicts", detail_source)
        self.assertIn(
            "state.rankingRequestId += 1", self.function_source("hideRanking")
        )
        self.assertIn(
            "state.workerRequestId += 1", self.function_source("closeModal")
        )

    def test_worker_refresh_preserves_the_available_selection(self):
        source = self.function_source("loadWorkerStats")
        for marker in (
            "const previous = new Set(state.selectedWorkers)",
            "const available = new Set(rows.map(row => row.worker))",
            "[...previous].filter(worker => available.has(worker))",
            "preserveSelection && preserved.size",
        ):
            self.assertIn(marker, source)

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
