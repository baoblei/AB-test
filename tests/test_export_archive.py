import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app_core.errors import AppError
from app_core.schemas import ExportRequest
from app_core.storage import get_ref_image_path, get_result_image_path


def make_row(row_id=1, **overrides):
    row = {
        "id": row_id, "eval_mode": "full", "task_type": "TI2I", "v_a": "D", "v_b": "E",
        "scene": "portrait", "filename": "scene1.jpg", "overall": "D", "aesthetic": "D",
        "logic": "D", "consistency": "D", "fidelity": "D", "worker": "alice",
        "timestamp": "2026-07-15T12:00:00+08:00", "duration_seconds": 3, "skipped": 0,
        "user_id": 1, "bad_case_tags_a": "[]", "bad_case_tags_b": "[]",
        "bad_case_categories_a": "[]", "bad_case_categories_b": "[]",
    }
    row.update(overrides)
    return row


class ExportArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.results = root / "results"
        self.refs = root / "refs"
        for model in ("D", "E"):
            directory = self.results / model / "portrait"
            directory.mkdir(parents=True)
            (directory / "scene1.jpg").write_bytes(model.encode())
        (self.refs / "portrait").mkdir(parents=True)
        (self.refs / "portrait" / "scene1.jpg").write_bytes(b"ref")
        self.request = ExportRequest(task_type="TI2I", v1="D", v2="E", dimensions=["fidelity"], include_images=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def result_resolver(self, task_type, model, scene, filename):
        path = self.results / model / scene / filename
        return str(path) if path.is_file() else None

    def ref_resolver(self, task_type, scene, filename):
        path = self.refs / scene / filename
        return str(path) if path.is_file() else None

    def test_storage_image_paths_reject_unsafe_components(self):
        for value in ("", ".", "..", "a/b", "a\\b"):
            with self.subTest(value=value):
                with self.assertRaises(AppError):
                    get_result_image_path("T2I", value, "scene", "image.png")
                with self.assertRaises(AppError):
                    get_ref_image_path("TI2I", "scene", value)

    def test_archive_uses_scene_model_ref_layout_and_deduplicates_rows(self):
        from app_core.export_service import build_archive

        archive_path = Path(self.temp_dir.name) / "archive.zip"
        artifact = build_archive(
            self.request,
            workbook_data=b"xlsx",
            selected_rows=[make_row(), make_row(2, worker="bob")],
            result_path_resolver=self.result_resolver,
            ref_path_resolver=self.ref_resolver,
            archive_path=str(archive_path),
        )
        with zipfile.ZipFile(artifact, "r") as archive:
            self.assertEqual(
                sorted(archive.namelist()),
                ["images/portrait/D/scene1.jpg", "images/portrait/E/scene1.jpg", "images/portrait/ref/scene1.jpg", "评测结果.xlsx"],
            )

    def test_result_image_path_and_archive_fall_back_to_legacy_file_after_configured_scene(self):
        from app_core.export_service import build_archive, build_image_manifest

        configured_root = Path(self.temp_dir.name) / "configured"
        legacy_root = Path(self.temp_dir.name) / "legacy"
        for root in (configured_root, legacy_root):
            for model in ("D", "E"):
                (root / model / "portrait").mkdir(parents=True)
        for model in ("D", "E"):
            (legacy_root / model / "portrait" / "scene1.jpg").write_bytes(model.encode())
        request = ExportRequest(task_type="T2I", v1="D", v2="E", include_images=True)
        rows = [make_row(task_type="T2I")]

        with patch("app_core.storage.get_result_roots", return_value=[str(configured_root), str(legacy_root)]):
            self.assertEqual(
                get_result_image_path("T2I", "D", "portrait", "scene1.jpg"),
                str(legacy_root / "D" / "portrait" / "scene1.jpg"),
            )
            manifest = build_image_manifest(request, rows, result_path_resolver=get_result_image_path)

        archive_path = Path(self.temp_dir.name) / "legacy-fallback.zip"
        build_archive(request, b"xlsx", rows, archive_path=str(archive_path), image_manifest=manifest)
        with zipfile.ZipFile(archive_path, "r") as archive:
            self.assertEqual(
                sorted(archive.namelist()),
                ["images/portrait/D/scene1.jpg", "images/portrait/E/scene1.jpg", "评测结果.xlsx"],
            )

    def test_missing_image_is_not_written_and_workbook_marks_manifest_status(self):
        from app_core.export_service import build_image_manifest, build_workbook, workbook_bytes

        manifest = build_image_manifest(self.request, [make_row()], lambda *args: None, lambda *args: None)
        self.assertEqual(manifest[("portrait", "scene1.jpg")]["D"]["status"], "文件不存在")
        workbook = build_workbook(self.request, [make_row()], image_manifest=manifest)
        sheet = load_workbook(BytesIO(workbook_bytes(workbook)))["保真度明细"]
        headers = [cell.value for cell in sheet[1]]
        self.assertEqual(sheet.cell(2, headers.index("D 图片路径") + 1).value, "images/portrait/D/scene1.jpg")
        self.assertEqual(sheet.cell(2, headers.index("D 图片状态") + 1).value, "文件不存在")

    def test_create_artifact_rejects_empty_overall_and_cleans_failed_temp_directory(self):
        from app_core import export_service

        with patch.object(export_service, "fetch_base_rows", return_value=[]):
            with self.assertRaisesRegex(AppError, "没有符合条件的评测记录"):
                export_service.create_export_artifact(self.request)

        temp_root = Path(self.temp_dir.name) / "export-root"
        temp_root.mkdir()
        with patch.object(export_service, "fetch_base_rows", return_value=[make_row()]):
            with patch.object(export_service.tempfile, "mkdtemp", return_value=str(temp_root / "artifact")):
                with patch.object(export_service, "build_workbook", side_effect=OSError("write failed")):
                    with self.assertRaises(OSError):
                        export_service.create_export_artifact(self.request)
        self.assertFalse((temp_root / "artifact").exists())


class ExportApiTests(unittest.TestCase):
    def test_new_export_routes_preserve_legacy_get_and_return_file_response(self):
        import main
        from app_core.export_service import ExportArtifact

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "评测结果.xlsx"
            path.write_bytes(b"xlsx")
            artifact = ExportArtifact(str(path), "评测结果.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", temp_dir)
            with patch.object(main, "export_results", return_value={"legacy": True}):
                with patch.object(main, "get_export_options", return_value={"total": 1}) as options:
                    with patch.object(main, "preview_export", return_value={"overall": 1}) as preview:
                        with patch.object(main, "create_export_artifact", return_value=artifact) as create:
                            client = TestClient(main.app)
                            self.assertEqual(client.get("/api/export", params={"format": "json"}).status_code, 200)
                            self.assertEqual(client.get("/api/export_options", params={"task_type": "T2I", "v1": "A", "v2": "B"}).json(), {"total": 1})
                            self.assertEqual(client.post("/api/export/preview", json={"task_type": "T2I", "v1": "A", "v2": "B"}).json(), {"overall": 1})
                            response = client.post("/api/export", json={"task_type": "T2I", "v1": "A", "v2": "B"})
            options.assert_called_once_with("T2I", "A", "B")
            preview.assert_called_once()
            create.assert_called_once()
            self.assertEqual(response.headers["content-type"], artifact.media_type)
            self.assertIn("filename*=utf-8''", response.headers["content-disposition"])
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
