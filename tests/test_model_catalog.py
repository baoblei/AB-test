import io
import os
import sqlite3
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from app_core import config, model_catalog, storage
from app_core.errors import AppError
from app_core.model_catalog import compose_model_name, parse_model_name, validate_model_component


class ModelNameTests(unittest.TestCase):
    def test_composes_three_valid_components(self):
        self.assertEqual(
            compose_model_name("test", "Atlas", "default"),
            "test_Atlas_default",
        )

    def test_rejects_empty_underscore_and_unsafe_components(self):
        for value in ("", "   ", "foo_bar", ".", "..", "nested/path", "nested\\path"):
            with self.subTest(value=value):
                with self.assertRaises(AppError):
                    validate_model_component(value, "class")

    def test_parses_exactly_three_non_empty_parts(self):
        self.assertEqual(
            parse_model_name("test_Atlas_default"),
            {
                "class_name": "test",
                "model_name": "Atlas",
                "version": "default",
                "full_name": "test_Atlas_default",
            },
        )

    def test_preserves_non_standard_legacy_name(self):
        for full_name in ("Atlas", "too_many_parts_here", "broken__name"):
            with self.subTest(full_name=full_name):
                self.assertEqual(
                    parse_model_name(full_name),
                    {
                        "class_name": None,
                        "model_name": None,
                        "version": full_name,
                        "full_name": full_name,
                    },
                )


class ModelCatalogTests(unittest.TestCase):
    def test_merges_filesystem_and_database_names_with_legacy_compatibility(self):
        with patch.object(
            storage,
            "get_filesystem_model_names",
            return_value=["test_Atlas_default", "legacy-only"],
        ), patch.object(
            model_catalog,
            "get_database_model_names",
            return_value=["test_Atlas_default", "test_Beacon_default", "db-legacy"],
        ):
            self.assertEqual(
                model_catalog.get_model_catalog("T2I"),
                {
                    "task_type": "T2I",
                    "models": [
                        parse_model_name("db-legacy"),
                        parse_model_name("legacy-only"),
                        parse_model_name("test_Atlas_default"),
                        parse_model_name("test_Beacon_default"),
                    ],
                },
            )

    def test_database_discovery_reads_both_model_columns_from_both_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "catalog.db")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE pair_tasks (task_type TEXT, v_a TEXT, v_b TEXT)")
            conn.execute("CREATE TABLE results_log (task_type TEXT, v_a TEXT, v_b TEXT)")
            conn.execute(
                "INSERT INTO pair_tasks (task_type, v_a, v_b) VALUES ('T2I', 'pair-a', 'shared')"
            )
            conn.execute(
                "INSERT INTO results_log (task_type, v_a, v_b) VALUES ('T2I', 'shared', 'result-b')"
            )
            conn.execute(
                "INSERT INTO results_log (task_type, v_a, v_b) VALUES ('TI2I', 'other-task', 'ignored')"
            )
            conn.commit()
            conn.close()

            with patch.object(
                model_catalog,
                "connect",
                side_effect=lambda: sqlite3.connect(db_path),
            ):
                self.assertEqual(
                    model_catalog.get_database_model_names("T2I"),
                    ["pair-a", "result-b", "shared"],
                )


class ModelCatalogRouteTests(unittest.TestCase):
    def test_catalog_route_is_registered(self):
        import main

        routes = {route.path: route for route in main.app.routes}
        self.assertIn("/api/model_catalog", routes)


def image_zip(name: str) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(name, b"image")
    return data.getvalue()


class StructuredUploadTests(unittest.TestCase):
    def test_upload_builds_trusted_full_name_and_returns_it(self):
        upload = SimpleNamespace(file=io.BytesIO(image_zip("img.png")))
        with tempfile.TemporaryDirectory() as temp_dir:
            task_configs = {
                **config.TASK_CONFIGS,
                "T2I": {
                    **config.TASK_CONFIGS["T2I"],
                    "result_root": os.path.join(temp_dir, "results", "T2I"),
                },
            }
            with patch.object(config, "TASK_CONFIGS", task_configs), patch.object(
                storage,
                "validate_result_zip",
                return_value={"status": "exact", "rename_map": {}, "image_count": 1},
            ):
                result = storage.upload_result_zip(
                    "T2I", "test", "Atlas", "default", "scene", upload
                )

            expected = os.path.join(
                task_configs["T2I"]["result_root"],
                "test_Atlas_default",
                "scene",
                "img.png",
            )
            self.assertTrue(os.path.exists(expected))
            self.assertEqual(result["full_name"], "test_Atlas_default")

    def test_upload_rejects_underscore_before_writing(self):
        upload = SimpleNamespace(file=io.BytesIO(image_zip("img.png")))
        with self.assertRaises(AppError):
            storage.upload_result_zip(
                "T2I", "bad_class", "Atlas", "default", "scene", upload
            )


class StructuredUploadRouteTests(unittest.TestCase):
    def test_upload_route_accepts_separate_name_components(self):
        import main

        route = next(route for route in main.app.routes if route.path == "/api/upload")
        body_names = {field.name for field in route.dependant.body_params}
        self.assertTrue({"class_name", "model_name", "version"}.issubset(body_names))
        self.assertNotIn("full_name", body_names)


if __name__ == "__main__":
    unittest.main()
