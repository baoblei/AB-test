import json
import re
import subprocess
import unittest
from pathlib import Path


class DashboardExportUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/dashboard.html").read_text(encoding="utf-8")

    def function_source(self, name):
        start = self.html.index(f"function {name}")
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

    def run_function(self, name, arguments):
        source = self.function_source(name)
        script = f"{source}\nconsole.log(JSON.stringify({name}(...{json.dumps(arguments)})));"
        return json.loads(subprocess.check_output(["node", "-e", script], text=True))

    def run_invalid_export_render(self, downloading):
        script = f"""
            const elements = {{
                "export-preview-count": {{ textContent: "Overall 9 条" }},
                "export-message": {{ textContent: "正在生成下载文件..." }},
                "export-download": {{ disabled: true, textContent: "正在生成..." }}
            }};
            const document = {{ getElementById: id => elements[id] }};
            const state = {{ exportPair: {{
                previewAvailableCount: 9,
                downloading: {str(downloading).lower()},
                options: {{ dimensions: [{{ key: "aesthetic", label: "美学" }}, {{ key: "fidelity", label: "保真度" }}] }}
            }} }};
            {self.function_source("renderExportPreview")}
            {self.function_source("renderInvalidExportSelection")}
            renderInvalidExportSelection("请至少选择一个场景");
            console.log(JSON.stringify({{
                previewAvailableCount: state.exportPair.previewAvailableCount,
                preview: elements["export-preview-count"].textContent,
                message: elements["export-message"].textContent,
                disabled: elements["export-download"].disabled,
                buttonText: elements["export-download"].textContent
            }}));
        """
        return json.loads(subprocess.check_output(["node", "-e", script], text=True))

    def test_export_button_and_modal_exist_without_inline_model_calls(self):
        for marker in (
            'id="export-modal"',
            'id="export-form"',
            '"btn btn-export btn-sm"',
            'data-export-pair-index',
            'openExportModal(',
        ):
            self.assertIn(marker, self.html)

        self.assertNotRegex(
            self.html,
            r"openExportModal\(\s*['\"]?\$\{\s*pair\.(?:v_a|v_b)",
        )

    def test_export_filters_and_actions_exist(self):
        for marker in (
            'id="export-scenes"',
            'id="export-dimensions"',
            'id="export-workers"',
            'id="export-start-time"',
            'id="export-end-time"',
            'id="export-eval-modes"',
            'id="export-result-filter"',
            'id="export-bad-case-filter"',
            'id="export-images"',
            'id="export-bad-cases"',
            'id="export-duration"',
            'function collectExportRequest',
            'async function previewExport',
            'async function downloadExport',
            'function extractDownloadFilename',
            'function closeExportModal',
        ):
            self.assertIn(marker, self.html)

    def test_export_options_supply_dynamic_t2i_and_ti2i_dimensions(self):
        self.assertIn("options.dimensions", self.html)
        self.assertIn("renderExportChoices(\"export-dimensions\"", self.html)
        self.assertIn("option.label || option.key", self.html)
        self.assertIn("document.createTextNode(label)", self.html)

    def test_result_scene_selector_treats_uploaded_scene_names_as_text(self):
        malicious_scene = 'x" onclick="globalThis.injected=true'
        script = f"""
            const select = {{
                value: "",
                children: [],
                replaceChildren(...children) {{ this.children = children; }}
            }};
            const taskType = {{ value: "TI2I" }};
            const document = {{
                getElementById(id) {{ return id === "result-scene" ? select : taskType; }},
                createElement(tag) {{ return {{ tag, value: "", textContent: "" }}; }}
            }};
            const api = async () => ({{ json: async () => [{json.dumps(malicious_scene)}] }});
            {self.function_source("replaceSelectOptions")}
            async {self.function_source("syncResultScenes")}
            syncResultScenes().then(() => console.log(JSON.stringify(select.children)));
        """

        children = json.loads(subprocess.check_output(["node", "-e", script], text=True))

        self.assertNotIn("innerHTML", self.function_source("syncResultScenes"))
        self.assertEqual(children[1]["value"], malicious_scene)
        self.assertEqual(children[1]["textContent"], malicious_scene)
        self.assertNotIn("onclick", children[1])

    def test_ranking_scene_selector_treats_overview_scene_names_as_text(self):
        malicious_scene = 'x"><img src=x onerror="globalThis.injected=true">'
        script = f"""
            const select = {{
                children: [],
                replaceChildren(...children) {{ this.children = children; }}
            }};
            const classFilter = {{
                value: "",
                replaceChildren(...children) {{ this.children = children; }}
            }};
            const modelFilter = {{
                value: "",
                replaceChildren(...children) {{ this.children = children; }}
            }};
            const status = {{ textContent: "" }};
            const document = {{
                getElementById(id) {{
                    if (id === "ranking-scene") return select;
                    if (id === "filter-class") return classFilter;
                    if (id === "filter-model") return modelFilter;
                    return status;
                }},
                createElement(tag) {{ return {{ tag, value: "", textContent: "" }}; }}
            }};
            const state = {{
                taskType: "T2I",
                overview: null,
                pairs: [],
                modelCatalogs: {{ T2I: [] }}
            }};
            const api = async () => ({{ json: async () => ({{
                pairs: [{{
                    v_a: "legacy-a",
                    v_b: "legacy-b",
                    scenes: [{{ scene: {json.dumps(malicious_scene)} }}]
                }}]
            }}) }});
            const applyFilters = () => {{}};
            const formatBeijingNow = () => "now";
            {self.function_source("replaceSelectOptions")}
            {self.function_source("uniqueSorted")}
            {self.function_source("catalogEntryFor")}
            {self.function_source("syncOverviewModelFilters")}
            async {self.function_source("loadDashboard")}
            loadDashboard().then(() => console.log(JSON.stringify(select.children)));
        """

        children = json.loads(subprocess.check_output(["node", "-e", script], text=True))

        self.assertNotIn("innerHTML", self.function_source("loadDashboard"))
        self.assertEqual(children[1]["value"], malicious_scene)
        self.assertEqual(children[1]["textContent"], malicious_scene)
        self.assertNotIn("onerror", children[1])

    def test_dynamic_dashboard_renderers_do_not_interpolate_backend_html(self):
        functions = (
            "handleTaskTypeChange",
            "renderPairs",
            "renderSummaryBox",
            "renderSceneRow",
            "loadRanking",
            "renderDetailWorkers",
            "renderDetailTable",
            "renderWorkerStats",
            "openBadcaseModal",
            "syncBadcaseTags",
            "loadBadcaseDetails",
            "openPreview",
            "buildBadCasePreviewPayload",
        )
        for name in functions:
            with self.subTest(name=name):
                source = self.function_source(name)
                self.assertNotIn("innerHTML", source)
                self.assertNotIn("onclick=", source)

    def test_ti2i_preview_keeps_model_labels_when_reference_image_is_missing(self):
        script = f"""
            const state = {{ taskType: "TI2I" }};
            const imageUrl = (model, scene, filename) => `${{model}}/${{scene}}/${{filename}}`;
            {self.function_source("buildPreviewPayload")}
            const payload = buildPreviewPayload(
                {{ ref_img: null, scene: "open", filename: "scene1.jpg" }},
                "model-a",
                "model-b"
            );
            console.log(JSON.stringify(payload));
        """
        payload = json.loads(subprocess.check_output(["node", "-e", script], text=True))

        self.assertIsNone(payload["ref"])
        self.assertEqual(payload["labels"], ["model-a", "model-b"])

    def test_beijing_datetime_is_appended_without_timezone_conversion(self):
        self.assertEqual(
            self.run_function("localInputToBeijingIso", ["2026-07-15T09:30", False]),
            "2026-07-15T09:30:00+08:00",
        )
        self.assertEqual(
            self.run_function("localInputToBeijingIso", ["2026-07-15T09:30", True]),
            "2026-07-15T09:30:59+08:00",
        )
        self.assertNotIn("new Date(value)", self.function_source("localInputToBeijingIso"))

    def test_preview_ignores_stale_response_and_gates_on_all_selected_results(self):
        self.assertIn("previewTimer", self.html)
        self.assertIn("previewController", self.html)
        self.assertIn("exportPreviewRequestId", self.html)
        self.assertIn("requestId !== state.exportPreviewRequestId", self.html)
        self.assertIn("function exportPreviewAvailableCount", self.html)
        self.assertNotIn("exportButton.disabled = preview.overall === 0;", self.html)
        self.assertIn("setTimeout", self.function_source("scheduleExportPreview"))

        script = f"""
            const exportButton = {{ disabled: true }};
            const previewCount = {{ textContent: "" }};
            const message = {{ textContent: "" }};
            const document = {{ getElementById: id => id === "export-download" ? exportButton : id === "export-preview-count" ? previewCount : message }};
            const state = {{
                exportPreviewRequestId: 0,
                modalSessionId: 1,
                exportPair: {{
                    options: {{ dimensions: [{{ key: "aesthetic", label: "美学" }}] }},
                    previewTimer: null,
                    previewController: null,
                    previewAvailableCount: 0,
                    sessionId: 1,
                    downloading: false
                }}
            }};
            const collectExportRequest = () => ({{ scenes: ["portrait"], workers: ["alice"], eval_modes: ["full"] }});
            const exportSelectionError = () => "";
            const isCurrentExportSession = sessionId => sessionId === 1;
            const setExportMessage = value => {{ message.textContent = value; }};
            const api = async () => ({{ json: async () => ({{ overall: 0, dimensions: {{ aesthetic: 1 }}, unique_images: 1 }}) }});
            {self.function_source("exportPreviewAvailableCount")}
            {self.function_source("renderExportPreview")}
            async {self.function_source("previewExport")}
            previewExport().then(() => console.log(JSON.stringify({{
                disabled: exportButton.disabled,
                available: state.exportPair.previewAvailableCount,
                message: message.textContent
            }})));
        """
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result, {"disabled": False, "available": 1, "message": ""})

    def test_empty_required_export_choices_are_blocked_before_preview_or_download(self):
        valid_request = {"scenes": ["portrait"], "workers": ["alice"], "eval_modes": ["full"]}
        for field, message in (
            ("scenes", "请至少选择一个场景"),
            ("workers", "请至少选择一位评测人"),
            ("eval_modes", "请至少选择一种评测模式"),
        ):
            request = dict(valid_request)
            request[field] = []
            with self.subTest(field=field):
                self.assertEqual(self.run_function("exportSelectionError", [request]), message)

        preview = self.function_source("previewExport")
        download = self.function_source("downloadExport")
        self.assertLess(preview.index("if (selectionError)"), preview.index('api("/api/export/preview"'))
        self.assertLess(download.index("if (selectionError)"), download.index('fetch("/api/export"'))
        invalid_render = self.function_source("renderInvalidExportSelection")
        self.assertIn("previewAvailableCount = 0", invalid_render)
        self.assertIn("exportButton.disabled = true", invalid_render)

    def test_invalid_selection_updates_counts_and_message_while_download_is_running(self):
        rendered = self.run_invalid_export_render(downloading=True)

        self.assertEqual(rendered["previewAvailableCount"], 0)
        self.assertEqual(rendered["preview"], "Overall 0 条 · 美学 0 · 保真度 0 · 去重图片 0 张")
        self.assertEqual(rendered["message"], "请至少选择一个场景")
        self.assertTrue(rendered["disabled"])
        self.assertEqual(rendered["buttonText"], "正在生成...")

    def test_download_session_tokens_prevent_old_download_from_mutating_new_modal(self):
        self.assertIn("modalSessionId", self.html)
        self.assertIn("downloadRequestId", self.html)
        self.assertIn("function isCurrentExportDownload", self.html)
        self.assertIn("state.modalSessionId += 1", self.function_source("closeExportModal"))
        self.assertIn('button.textContent = "下载导出"', self.function_source("openExportModal"))
        download = self.function_source("downloadExport")
        self.assertIn("const sessionId = state.modalSessionId", download)
        self.assertIn("const requestId = ++state.downloadRequestId", download)
        self.assertIn("if (!isCurrentExportDownload(sessionId, requestId)) return;", download)
        preview = self.function_source("previewExport")
        self.assertIn("if (!state.exportPair.downloading)", preview)

    def test_rfc5987_filename_parser_prefers_extended_filename(self):
        self.assertEqual(
            self.run_function(
                "extractDownloadFilename",
                ["attachment; filename=plain.xlsx; filename*=UTF-8''%E8%AF%84%E6%B5%8B.zip", True],
            ),
            "评测.zip",
        )
        self.assertEqual(
            self.run_function("extractDownloadFilename", ["attachment; filename=plain.xlsx", False]),
            "plain.xlsx",
        )
        self.assertEqual(
            self.run_function("extractDownloadFilename", [r'attachment; filename="a\"b.xlsx"', False]),
            'a"b.xlsx',
        )
        self.assertEqual(self.run_function("extractDownloadFilename", ["", True]), "评测导出.zip")


if __name__ == "__main__":
    unittest.main()
