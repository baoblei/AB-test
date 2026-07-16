import json
import re
import subprocess
import unittest
from pathlib import Path


class DashboardDatasetDownloadUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/dashboard.html").read_text(encoding="utf-8")

    def function_source(self, name):
        for prefix in (f"async function {name}", f"function {name}"):
            try:
                start = self.html.index(prefix)
                break
            except ValueError:
                continue
        else:
            self.fail(f"function {name} does not exist")
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

    def test_horizontal_layers_and_download_controls_exist(self):
        markers = (
            'class="card publish-card"',
            'class="card dataset-download-card"',
            'class="card statistics-filter-card"',
            'id="dataset-download-task-type"',
            'id="dataset-search"',
            'id="dataset-download-scene"',
            'id="dataset-include-ref"',
            'id="dataset-download-button"',
            'id="dataset-download-msg"',
        )
        for marker in markers:
            self.assertIn(marker, self.html)
        self.assertLess(self.html.index("publish-card"), self.html.index("dataset-download-card"))
        self.assertLess(self.html.index("dataset-download-card"), self.html.index("statistics-filter-card"))

    def test_checkbox_chip_input_cannot_inherit_viewport_wide_input_width(self):
        rule = re.search(r"\.checkbox-chip\s+input\s*\{([^}]*)\}", self.html)
        self.assertIsNotNone(rule)
        declarations = rule.group(1)
        self.assertRegex(declarations, r"\bwidth\s*:\s*auto\s*;")

    def test_existing_overview_actions_suppression_and_default_collapse_remain(self):
        for marker in ('"统计"', '"坏例详情"', '"导出"', '"明细"', '"坏例"', "renderSuppressionLine(stat)"):
            self.assertIn(marker, self.html)
        self.assertIn(
            'const body = createNode("div", `pair-body${state.expanded.has(pair.pair) ? " show" : ""}`)',
            self.html,
        )
        self.assertIn("expanded: new Set()", self.html)

    def run_mode_sync(self, task_type, checked):
        script = f"""
            const elements = {{
                "dataset-download-task-type": {{ value: {json.dumps(task_type)} }},
                "dataset-include-ref": {{ checked: {str(checked).lower()}, disabled: false }},
                "dataset-download-button": {{ textContent: "" }}
            }};
            const document = {{ getElementById: id => elements[id] }};
            {self.function_source("syncDatasetDownloadMode")}
            syncDatasetDownloadMode();
            console.log(JSON.stringify({{
                checked: elements["dataset-include-ref"].checked,
                disabled: elements["dataset-include-ref"].disabled,
                button: elements["dataset-download-button"].textContent
            }}));
        """
        return json.loads(subprocess.check_output(["node", "-e", script], text=True))

    def test_ti2i_reference_default_and_t2i_mode(self):
        self.assertEqual(
            self.run_mode_sync("T2I", checked=True),
            {"checked": False, "disabled": True, "button": "下载 TXT"},
        )
        self.assertEqual(
            self.run_mode_sync("TI2I", checked=False),
            {"checked": False, "disabled": False, "button": "下载 TXT"},
        )

    def test_search_filters_loaded_datasets_without_api_call(self):
        datasets = [
            {"scene": "人物写真", "prompt_count": 12},
            {"scene": "商品编辑", "prompt_count": 8},
        ]
        script = f"""
            const select = {{ value: "", children: [], replaceChildren(...nodes) {{ this.children = nodes; }} }};
            const elements = {{
                "dataset-search": {{ value: "商品" }},
                "dataset-download-scene": select,
                "dataset-download-task-type": {{ value: "T2I" }},
                "dataset-include-ref": {{ checked: false, disabled: false }},
                "dataset-download-button": {{ textContent: "" }}
            }};
            const document = {{
                getElementById: id => elements[id],
                createElement: tag => ({{ tag, value: "", textContent: "" }})
            }};
            const state = {{ datasets: {json.dumps(datasets, ensure_ascii=False)}, filteredDatasets: [] }};
            let apiCalls = 0;
            const api = () => {{ apiCalls += 1; }};
            {self.function_source("replaceSelectOptions")}
            {self.function_source("syncDatasetDownloadMode")}
            {self.function_source("filterDatasets")}
            filterDatasets();
            console.log(JSON.stringify({{
                options: select.children.slice(1).map(node => ({{ value: node.value, text: node.textContent }})),
                apiCalls,
                filtered: state.filteredDatasets
            }}));
        """
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result["options"], [{"value": "商品编辑", "text": "商品编辑（8 条）"}])
        self.assertEqual(result["apiCalls"], 0)
        self.assertEqual(result["filtered"], [datasets[1]])

    def test_load_datasets_ignores_out_of_order_responses_and_pending_mode_change(self):
        script = f"""
            const select = {{ value: "", children: [], replaceChildren(...nodes) {{ this.children = nodes; }} }};
            const elements = {{
                "dataset-download-task-type": {{ value: "T2I" }},
                "dataset-download-msg": {{ textContent: "" }},
                "dataset-search": {{ value: "" }},
                "dataset-download-scene": select,
                "dataset-include-ref": {{ checked: true, disabled: false }},
                "dataset-download-button": {{ textContent: "" }}
            }};
            const document = {{
                getElementById: id => elements[id],
                createElement: tag => ({{ tag, value: "", textContent: "" }})
            }};
            const state = {{ datasets: [], filteredDatasets: [], datasetListRequestId: 0 }};
            const pending = {{}};
            const api = url => new Promise(resolve => {{ pending[url] = resolve; }});
            {self.function_source("replaceSelectOptions")}
            {self.function_source("syncDatasetDownloadMode")}
            {self.function_source("filterDatasets")}
            {self.function_source("loadDatasets")}
            const first = loadDatasets("old");
            elements["dataset-download-task-type"].value = "TI2I";
            const second = loadDatasets("new");
            pending["/api/datasets?task_type=TI2I"]({{ json: async () => [{{ scene: "new", prompt_count: 2 }}] }});
            second.then(async () => {{
                pending["/api/datasets?task_type=T2I"]({{ json: async () => [{{ scene: "old", prompt_count: 1 }}] }});
                await first;
                console.log(JSON.stringify({{
                    datasets: state.datasets,
                    options: select.children.map(node => node.value),
                    selected: select.value,
                    includeRefDisabled: elements["dataset-include-ref"].disabled,
                    message: elements["dataset-download-msg"].textContent
                }}));
            }});
        """
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result["datasets"], [{"scene": "new", "prompt_count": 2}])
        self.assertEqual(result["options"], ["", "new"])
        self.assertEqual(result["selected"], "new")
        self.assertFalse(result["includeRefDisabled"])
        self.assertEqual(result["message"], "")

    def test_dataset_filename_parses_supported_headers_and_uses_scene_fallback(self):
        cases = (
            ("attachment; filename=plain.txt; filename*=UTF-8''%E4%BA%BA%E5%83%8F.txt", "人物", False, "人像.txt"),
            (r'attachment; filename="商品编辑.zip"', "ignored", True, "商品编辑.zip"),
            ("", "人物写真", False, "人物写真.txt"),
            ("attachment; filename*=UTF-8''%ZZ", "商品/编辑", True, "商品_编辑.zip"),
        )
        source = self.function_source("extractDatasetDownloadFilename")
        for header, scene, include_ref, expected in cases:
            with self.subTest(header=header, include_ref=include_ref):
                script = f"{source}\nconsole.log(JSON.stringify(extractDatasetDownloadFilename(...{json.dumps([header, scene, include_ref], ensure_ascii=False)})));"
                actual = json.loads(subprocess.check_output(["node", "-e", script], text=True))
                self.assertEqual(actual, expected)

    def test_download_uses_zip_only_for_checked_ti2i(self):
        script = f"""
            const elements = {{
                "dataset-download-task-type": {{ value: "TI2I" }},
                "dataset-download-scene": {{ value: "商品编辑" }},
                "dataset-include-ref": {{ checked: true, disabled: false }},
                "dataset-download-button": {{ disabled: false, textContent: "" }},
                "dataset-download-msg": {{ textContent: "" }}
            }};
            const document = {{
                getElementById: id => elements[id],
                createElement: () => ({{ click() {{}}, remove() {{}} }}),
                body: {{ append() {{}} }}
            }};
            let requested = "";
            const fetch = async url => {{
                requested = url;
                return {{ ok: true, blob: async () => ({{}}), headers: {{ get: () => null }} }};
            }};
            const URL = {{ createObjectURL: () => "blob:test", revokeObjectURL() {{}} }};
            const extractDownloadFilename = (_, includeRef) => includeRef ? "dataset.zip" : "dataset.txt";
            {self.function_source("syncDatasetDownloadMode")}
            {self.function_source("downloadDataset")}
            downloadDataset().then(() => console.log(JSON.stringify({{ requested }})));
        """
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(
            result["requested"],
            "/api/datasets/download?task_type=TI2I&scene=%E5%95%86%E5%93%81%E7%BC%96%E8%BE%91&include_ref=true",
        )

    def test_backend_dataset_names_are_added_as_text_nodes(self):
        self.assertNotIn("innerHTML", self.function_source("filterDatasets"))


if __name__ == "__main__":
    unittest.main()
