import json
import subprocess
import unittest
from pathlib import Path


class EvaluationShortcutsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/index.html").read_text(encoding="utf-8")

    def run_shortcut(self, selected, key):
        start = self.html.index(
            '        document.addEventListener("keydown", event => {',
            self.html.index('document.addEventListener("keyup", event => {'),
        )
        end = self.html.index("\n\n        init();", start)
        source = self.html[start:end]
        script = f"""
const vm = require("vm");
const selected = {json.dumps(selected)};
const clicked = [];
const listeners = {{}};
const dims = [
    {{ key: "overall", label: "整体" }},
    {{ key: "aesthetic", label: "美学" }},
    {{ key: "logic", label: "逻辑" }}
];
const context = {{
    state: {{ config: {{}} }},
    currentDimIndex: 0,
    getActiveEvalDims: () => dims,
    submitVote: () => {{}},
    document: {{
        addEventListener(type, handler) {{ listeners[type] = handler; }},
        querySelector(selector) {{
            const match = selector.match(/^input\\[name="([^"]+)"\\]:checked$/);
            return match && selected[match[1]] ? {{ checked: true }} : null;
        }},
        getElementById(id) {{
            if (id === "test-ui") return {{ classList: {{ contains: () => false }} }};
            return {{ click: () => clicked.push(id) }};
        }}
    }}
}};
vm.createContext(context);
vm.runInContext({json.dumps(source)}, context);
listeners.keydown({{ key: {json.dumps(key)}, target: {{ tagName: "BODY" }}, preventDefault() {{}} }});
console.log(JSON.stringify({{ clicked }}));
"""
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def test_shortcut_uses_first_unselected_dimension(self):
        for key, choice in (("1", "left"), ("2", "tie"), ("3", "right")):
            with self.subTest(key=key):
                result = self.run_shortcut(selected={"overall": "left"}, key=key)
                self.assertEqual(result["clicked"], [f"opt-aesthetic-{choice}"])

    def test_shortcut_does_not_overwrite_when_all_dimensions_are_selected(self):
        result = self.run_shortcut(
            selected={"overall": "left", "aesthetic": "tie", "logic": "right"},
            key="3",
        )
        self.assertEqual(result["clicked"], [])


if __name__ == "__main__":
    unittest.main()
