import json
import subprocess
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class DashboardDetailPerformanceUiTests(unittest.TestCase):
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

    def test_detail_pagination_controls_and_fixed_page_size_exist(self):
        for marker in (
            'id="detail-pagination"',
            'id="detail-page-prev"',
            'id="detail-page-status"',
            'id="detail-page-next"',
            "const DETAIL_PAGE_SIZE = 50",
            "function paginateDetailRows(",
            "function changeDetailPage(",
        ):
            self.assertIn(marker, self.html, f"missing dashboard marker: {marker}")

    def test_pagination_caps_rows_and_clamps_out_of_range_pages(self):
        source = self.function_source("paginateDetailRows")
        result = self.run_node(
            f"""
{source}
const rows = Array.from({{ length: 121 }}, (_, index) => index);
const first = paginateDetailRows(rows, 1, 50);
const last = paginateDetailRows(rows, 99, 50);
console.log(JSON.stringify({{
    first: {{ page: first.page, totalPages: first.totalPages, count: first.items.length, item: first.items[0] }},
    last: {{ page: last.page, totalPages: last.totalPages, count: last.items.length, item: last.items[0] }}
}}));
"""
        )
        self.assertEqual(
            result,
            {
                "first": {"page": 1, "totalPages": 3, "count": 50, "item": 0},
                "last": {"page": 3, "totalPages": 3, "count": 21, "item": 100},
            },
        )

    def test_detail_thumbnail_urls_encode_result_and_reference_identity(self):
        source = self.function_source("detailThumbnailUrl")
        result = self.run_node(
            f"""
const state = {{ taskType: "TI2I" }};
{source}
console.log(JSON.stringify({{
    result: detailThumbnailUrl("result", "model A", "scene 1", "image 1.png"),
    ref: detailThumbnailUrl("ref", "", "scene 1", "image 1.png")
}}));
"""
        )

        result_url = urlsplit(result["result"])
        ref_url = urlsplit(result["ref"])
        self.assertEqual(result_url.path, "/api/image-thumbnail")
        self.assertEqual(ref_url.path, "/api/image-thumbnail")
        self.assertEqual(
            parse_qs(result_url.query),
            {
                "kind": ["result"],
                "task_type": ["TI2I"],
                "scene": ["scene 1"],
                "filename": ["image 1.png"],
                "model": ["model A"],
            },
        )
        self.assertNotIn("model", parse_qs(ref_url.query))

    def test_detail_renderer_uses_only_the_current_page(self):
        source = self.function_source("renderDetailTable")
        for marker in (
            "paginateDetailRows(rows, state.detailPage, DETAIL_PAGE_SIZE)",
            "state.detailPage = pagination.page",
            "pagination.items.map(row =>",
            'document.getElementById("detail-page-status")',
            'document.getElementById("detail-page-prev").disabled',
            'document.getElementById("detail-page-next").disabled',
        ):
            self.assertIn(marker, source)
        self.assertNotIn("...rows.map(row =>", source)

    def test_detail_list_loads_thumbnails_but_click_preview_keeps_originals(self):
        renderer = self.function_source("renderDetailTable")
        for marker in (
            'detailThumbnailUrl("ref", "", scene, row.filename)',
            'detailThumbnailUrl("result", model, scene, row.filename)',
            'image.loading = "lazy"',
            'image.decoding = "async"',
            'image.fetchPriority = "low"',
            "image.width = 76",
            "image.height = 76",
            'image.addEventListener("click", () => openPreview(preview))',
        ):
            self.assertIn(marker, renderer)
        self.assertNotIn("image.src = imageUrl(", renderer)
        self.assertNotIn("image.src = row.ref_img", renderer)

        payload = self.function_source("buildPreviewPayload")
        compare_box = self.function_source("createCompareBox")
        open_preview = self.function_source("openPreview")
        self.assertIn("imageUrl(v1, row.scene, row.filename)", payload)
        self.assertIn("imageUrl(v2, row.scene, row.filename)", payload)
        self.assertIn("image.src = src", compare_box)
        self.assertIn("createCompareBox", open_preview)

    def test_detail_filters_reset_page_and_filename_search_is_debounced(self):
        self.assertIn(
            'id="detail-filename-filter" placeholder="输入关键词..." oninput="scheduleDetailRender()"',
            self.html,
        )
        self.assertIn(
            'id="detail-result-filter" onchange="resetDetailPage()"', self.html
        )
        schedule = self.function_source("scheduleDetailRender")
        toggle_worker = self.function_source("toggleDetailWorker")
        self.assertIn("clearTimeout(state.detailRenderTimer)", schedule)
        self.assertIn("setTimeout", schedule)
        self.assertIn("resetDetailPage()", schedule)
        self.assertIn(", 200)", schedule)
        self.assertIn("resetDetailPage()", toggle_worker)

    def test_cleanup_releases_detail_rows_workers_and_image_nodes(self):
        source = self.function_source("cleanupDetailModal")
        result = self.run_node(
            f"""
const makeNode = () => ({{
    children: [1, 2], textContent: "old", disabled: false, style: {{ display: "flex" }},
    replaceChildren(...children) {{ this.children = children; }}
}});
const elements = {{
    "detail-body": makeNode(),
    "detail-worker-group": makeNode(),
    "detail-count": makeNode(),
    "detail-pagination": makeNode(),
    "detail-page-status": makeNode(),
    "detail-page-prev": makeNode(),
    "detail-page-next": makeNode()
}};
const document = {{ getElementById: id => elements[id] }};
let clearedTimer = null;
const clearTimeout = timer => {{ clearedTimer = timer; }};
const state = {{
    detailRows: [1, 2], selectedDetailWorkers: new Set(["alice"]),
    currentDetail: {{ scene: "old" }}, detailPage: 4,
    detailRenderTimer: 19, detailRequestId: 7
}};
{source}
cleanupDetailModal();
console.log(JSON.stringify({{
    rows: state.detailRows.length,
    workers: state.selectedDetailWorkers.size,
    currentDetail: state.currentDetail,
    page: state.detailPage,
    requestId: state.detailRequestId,
    clearedTimer,
    bodyChildren: elements["detail-body"].children.length,
    workerChildren: elements["detail-worker-group"].children.length,
    paginationDisplay: elements["detail-pagination"].style.display,
    status: elements["detail-page-status"].textContent
}}));
"""
        )
        self.assertEqual(
            result,
            {
                "rows": 0,
                "workers": 0,
                "currentDetail": None,
                "page": 1,
                "requestId": 8,
                "clearedTimer": 19,
                "bodyChildren": 0,
                "workerChildren": 0,
                "paginationDisplay": "none",
                "status": "第 1 / 1 页",
            },
        )

    def test_close_invalidates_late_detail_response(self):
        open_source = self.function_source("openDetailModal")
        cleanup_source = self.function_source("cleanupDetailModal")
        close_source = self.function_source("closeModal")
        self.assertIn("const requestId = ++state.detailRequestId", open_source)
        self.assertIn("requestId !== state.detailRequestId", open_source)
        self.assertIn('id === "detail-modal"', close_source)
        self.assertIn("cleanupDetailModal()", close_source)

        result = self.run_node(
            f"""
const makeNode = () => ({{
    value: "", textContent: "", disabled: false,
    children: [], style: {{ display: "none" }},
    replaceChildren(...children) {{ this.children = children; }}
}});
const elements = {{
    "detail-title": makeNode(), "detail-modal": makeNode(),
    "detail-filename-filter": makeNode(), "detail-result-filter": makeNode(),
    "detail-body": makeNode(), "detail-worker-group": makeNode(),
    "detail-count": makeNode(), "detail-pagination": makeNode(),
    "detail-page-status": makeNode(), "detail-page-prev": makeNode(),
    "detail-page-next": makeNode()
}};
const document = {{ getElementById: id => elements[id] }};
const state = {{
    taskType: "T2I", detailRows: [], selectedDetailWorkers: new Set(),
    currentDetail: null, detailPage: 1, detailRenderTimer: null,
    detailRequestId: 0
}};
const clearTimeout = () => {{}};
let resolveRequest;
const api = () => new Promise(resolve => {{ resolveRequest = resolve; }});
const renderDetailWorkers = () => {{ throw new Error("stale response rendered workers"); }};
const renderDetailTable = () => {{ throw new Error("stale response rendered table"); }};
{cleanup_source}
{open_source}
{close_source}
(async () => {{
    const pending = openDetailModal("a", "b", "scene");
    closeModal("detail-modal");
    resolveRequest({{ json: async () => [{{ worker: "late" }}] }});
    await pending;
    console.log(JSON.stringify({{
        rows: state.detailRows.length,
        currentDetail: state.currentDetail,
        modalDisplay: elements["detail-modal"].style.display
    }}));
}})();
"""
        )
        self.assertEqual(
            result, {"rows": 0, "currentDetail": None, "modalDisplay": "none"}
        )


if __name__ == "__main__":
    unittest.main()
