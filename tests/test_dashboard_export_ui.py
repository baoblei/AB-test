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

    def test_export_button_and_modal_exist_without_inline_model_calls(self):
        for marker in (
            'id="export-modal"',
            'id="export-form"',
            'class="btn btn-export btn-sm"',
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

    def test_preview_ignores_stale_response_and_disables_empty_overall(self):
        self.assertIn("previewTimer", self.html)
        self.assertIn("previewController", self.html)
        self.assertIn("exportPreviewRequestId", self.html)
        self.assertIn("if (requestId !== state.exportPreviewRequestId) return;", self.html)
        self.assertIn("exportButton.disabled = preview.overall === 0;", self.html)
        self.assertIn("setTimeout", self.function_source("scheduleExportPreview"))

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
        self.assertEqual(self.run_function("extractDownloadFilename", ["", True]), "评测导出.zip")


if __name__ == "__main__":
    unittest.main()
