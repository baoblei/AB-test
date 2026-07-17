import unittest
from pathlib import Path


class DashboardPermissionFeedbackTests(unittest.TestCase):
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

    def test_upload_feedback_has_success_and_error_states(self):
        self.assertIn(".status-success", self.html)
        self.assertIn(".status-error", self.html)
        self.assertIn('setUploadMessage(data.message || "上传成功", "success")', self.html)

    def test_status_helpers_clear_old_semantic_state_before_setting_new_state(self):
        for name, element_id in (
            ("setUploadMessage", "upload-msg"),
            ("setExportMessage", "export-message"),
        ):
            source = self.function_source(name)
            with self.subTest(name=name):
                self.assertIn(f'getElementById("{element_id}")', source)
                self.assertIn('classList.remove("status-success", "status-error")', source)
                self.assertIn('classList.add(`status-${status}`)', source)

    def test_new_requests_clear_semantic_feedback_state(self):
        dataset_upload = self.html[self.html.index('document.getElementById("dataset-form").onsubmit') :]
        self.assertIn('setUploadMessage("上传测评集中...")', dataset_upload)
        self.assertIn('setUploadMessage(autoRename ? "正在自动格式化名称并上传..." : "检查结果图 zip 中...")', self.function_source("uploadResultZip"))
        self.assertIn('setExportMessage("正在更新预计数量...")', self.function_source("previewExport"))
        self.assertIn('setExportMessage("正在生成下载文件...")', self.function_source("downloadExport"))

    def test_all_caught_upload_errors_are_red(self):
        bind = self.function_source("bindUploadForms")
        result_upload = self.function_source("uploadResultZip")
        self.assertIn('setUploadMessage(error.message, "error")', bind)
        self.assertIn('setUploadMessage(error.message, "error")', result_upload)

    def test_model_catalog_error_replaces_stale_upload_success_state(self):
        source = self.function_source("handleResultTaskTypeChange")
        self.assertIn(
            'setUploadMessage(`模型目录加载失败，仍可手动输入：${error}`, "error")',
            source,
        )
        self.assertNotIn('getElementById("upload-msg").textContent', source)

    def test_export_failures_use_normalized_api_detail_and_red_feedback(self):
        api = self.function_source("api")
        self.assertIn("data.detail || data.message || message", api)
        self.assertIn('setExportMessage(error.message, "error")', self.function_source("openExportModal"))
        self.assertIn('setExportMessage(error.message, "error")', self.function_source("previewExport"))
        self.assertIn('setExportMessage(error.message, "error")', self.function_source("downloadExport"))

    def test_successful_upload_and_download_feedback_is_green(self):
        self.assertIn('setUploadMessage(data.message || "上传成功", "success")', self.function_source("bindUploadForms"))
        self.assertIn('setUploadMessage(`结果图上传成功：${result.full_name}，${result.image_count || 0} 张`, "success")', self.function_source("uploadResultZip"))
        self.assertIn('setExportMessage("下载已开始", "success")', self.function_source("downloadExport"))


if __name__ == "__main__":
    unittest.main()
