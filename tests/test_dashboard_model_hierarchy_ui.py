import json
import subprocess
import unittest
from pathlib import Path


class DashboardModelHierarchyUiTests(unittest.TestCase):
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

    def run_js(self, body):
        return json.loads(subprocess.check_output(["node", "-e", body], text=True))

    def test_upload_and_filter_controls_exist(self):
        for marker in (
            'id="result-class"',
            'id="result-model"',
            'id="result-version"',
            'id="result-class-options"',
            'id="result-model-options"',
            'id="result-version-options"',
            'id="filter-class"',
            'id="filter-model"',
        ):
            self.assertIn(marker, self.html)

    def test_form_data_submits_components_not_full_name(self):
        source = self.function_source("uploadResultZip")
        self.assertIn('formData.append("class_name"', source)
        self.assertIn('formData.append("model_name"', source)
        self.assertIn('formData.append("version"', source)
        self.assertNotIn('formData.append("full_name"', source)

    def test_pair_hierarchy_must_match_on_the_same_side(self):
        source = self.function_source("pairMatchesHierarchy")
        payload = self.run_js(
            f"""
            {source}
            const pair = {{
                v_a_meta: {{ class_name: "alpha", model_name: "one" }},
                v_b_meta: {{ class_name: "beta", model_name: "two" }}
            }};
            console.log(JSON.stringify([
                pairMatchesHierarchy(pair, "alpha", "one"),
                pairMatchesHierarchy(pair, "alpha", "two"),
                pairMatchesHierarchy(pair, "", ""),
            ]));
            """
        )
        self.assertEqual(payload, [True, False, True])

    def test_legacy_null_model_only_matches_all(self):
        source = self.function_source("pairMatchesHierarchy")
        payload = self.run_js(
            f"""
            {source}
            const pair = {{
                v_a_meta: {{ class_name: null, model_name: null }},
                v_b_meta: {{ class_name: null, model_name: null }}
            }};
            console.log(JSON.stringify([
                pairMatchesHierarchy(pair, "", ""),
                pairMatchesHierarchy(pair, "test", ""),
            ]));
            """
        )
        self.assertEqual(payload, [True, False])

    def test_model_input_validation_rejects_underscore_and_paths(self):
        source = self.function_source("validateModelInput")
        payload = self.run_js(
            f"""
            {source}
            const values = ["good", "bad_name", "../bad", ""];
            console.log(JSON.stringify(values.map(value => {{
                try {{ return validateModelInput(value, "class"); }}
                catch (error) {{ return error.message; }}
            }})));
            """
        )
        self.assertEqual(
            payload,
            ["good", "class 不能包含下划线 _", "class 包含不安全字符", "请输入 class"],
        )

    def test_new_class_confirmation_precedes_new_model_confirmation(self):
        sources = "\n".join(
            self.function_source(name)
            for name in ("currentResultCatalog", "validateModelInput", "confirmNewModelHierarchy")
        )
        payload = self.run_js(
            f"""
            const events = [];
            const elements = {{
                "result-task-type": {{ value: "T2I" }},
                "result-class": {{ value: "fresh", focus() {{ events.push("focus-class"); }} }},
                "result-model": {{ value: "model", focus() {{ events.push("focus-model"); }} }},
                "result-version": {{ value: "v1" }}
            }};
            const document = {{ getElementById: id => elements[id] }};
            const state = {{ modelCatalogs: {{ T2I: [] }} }};
            const confirm = message => {{ events.push(message); return true; }};
            {sources}
            console.log(JSON.stringify({{ result: confirmNewModelHierarchy(), events }}));
            """
        )
        self.assertTrue(payload["result"])
        self.assertEqual(
            payload["events"],
            [
                "class “fresh” 尚不存在，是否新建？",
                "model “model” 尚不存在，是否在 class “fresh” 下新建？",
            ],
        )

    def test_cancelling_new_class_keeps_input_and_focuses_it(self):
        sources = "\n".join(
            self.function_source(name)
            for name in ("currentResultCatalog", "validateModelInput", "confirmNewModelHierarchy")
        )
        payload = self.run_js(
            f"""
            const events = [];
            const elements = {{
                "result-task-type": {{ value: "T2I" }},
                "result-class": {{ value: "fresh", focus() {{ events.push("focus-class"); }} }},
                "result-model": {{ value: "model", focus() {{ events.push("focus-model"); }} }},
                "result-version": {{ value: "v1" }}
            }};
            const document = {{ getElementById: id => elements[id] }};
            const state = {{ modelCatalogs: {{ T2I: [] }} }};
            const confirm = message => {{ events.push(message); return false; }};
            {sources}
            console.log(JSON.stringify({{ result: confirmNewModelHierarchy(), events }}));
            """
        )
        self.assertFalse(payload["result"])
        self.assertEqual(
            payload["events"],
            ["class “fresh” 尚不存在，是否新建？", "focus-class"],
        )

    def test_existing_class_only_confirms_new_model(self):
        sources = "\n".join(
            self.function_source(name)
            for name in ("currentResultCatalog", "validateModelInput", "confirmNewModelHierarchy")
        )
        payload = self.run_js(
            f"""
            const events = [];
            const elements = {{
                "result-task-type": {{ value: "T2I" }},
                "result-class": {{ value: "test", focus() {{ events.push("focus-class"); }} }},
                "result-model": {{ value: "new-model", focus() {{ events.push("focus-model"); }} }},
                "result-version": {{ value: "v1" }}
            }};
            const document = {{ getElementById: id => elements[id] }};
            const state = {{ modelCatalogs: {{ T2I: [{{
                class_name: "test", model_name: "Atlas", version: "default"
            }}] }} }};
            const confirm = message => {{ events.push(message); return true; }};
            {sources}
            console.log(JSON.stringify({{ result: confirmNewModelHierarchy(), events }}));
            """
        )
        self.assertTrue(payload["result"])
        self.assertEqual(
            payload["events"],
            ["model “new-model” 尚不存在，是否在 class “test” 下新建？"],
        )

    def test_result_choices_cascade_by_class_and_model(self):
        sources = "\n".join(
            self.function_source(name)
            for name in (
                "replaceDatalistOptions",
                "currentResultCatalog",
                "uniqueSorted",
                "syncResultModelChoices",
            )
        )
        payload = self.run_js(
            f"""
            const lists = {{
                "result-class-options": {{ replaceChildren(...nodes) {{ this.values = nodes.map(n => n.value); }} }},
                "result-model-options": {{ replaceChildren(...nodes) {{ this.values = nodes.map(n => n.value); }} }},
                "result-version-options": {{ replaceChildren(...nodes) {{ this.values = nodes.map(n => n.value); }} }}
            }};
            const elements = {{
                "result-task-type": {{ value: "T2I" }},
                "result-class": {{ value: "test" }},
                "result-model": {{ value: "Atlas" }},
                ...lists
            }};
            const document = {{
                getElementById: id => elements[id],
                createElement: () => ({{ value: "" }})
            }};
            const state = {{ modelCatalogs: {{ T2I: [
                {{ class_name: "test", model_name: "Atlas", version: "default" }},
                {{ class_name: "test", model_name: "Atlas", version: "v2" }},
                {{ class_name: "test", model_name: "Beacon", version: "default" }},
                {{ class_name: "other", model_name: "Hidden", version: "v1" }},
                {{ class_name: null, model_name: null, version: "legacy" }}
            ] }} }};
            {sources}
            syncResultModelChoices();
            console.log(JSON.stringify({{
                classes: lists["result-class-options"].values,
                models: lists["result-model-options"].values,
                versions: lists["result-version-options"].values
            }}));
            """
        )
        self.assertEqual(payload["classes"], ["other", "test"])
        self.assertEqual(payload["models"], ["Atlas", "Beacon"])
        self.assertEqual(payload["versions"], ["default", "v2"])

    def test_each_upload_block_has_two_rows(self):
        for marker in (
            'class="upload-row dataset-upload-primary"',
            'class="upload-row dataset-upload-files"',
            'class="upload-row result-upload-primary"',
            'class="upload-row result-upload-files"',
        ):
            self.assertIn(marker, self.html)

    def test_mobile_upload_rows_collapse_to_one_column(self):
        mobile = self.html[self.html.index("@media (max-width: 720px)") :]
        self.assertIn(".upload-row", mobile)
        self.assertIn("grid-template-columns: 1fr", mobile)


if __name__ == "__main__":
    unittest.main()
