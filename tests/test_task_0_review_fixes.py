import asyncio
import io
import os
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import main
from app_core import config, storage
from app_core.errors import AppError


def image_zip(*names: str) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name in names:
            archive.writestr(name, b"image")
    return data.getvalue()


class ResultRootResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.result_root = os.path.join(self.temp_dir.name, "results")
        self.configured_root = os.path.join(self.result_root, "T2I")
        self.task_configs = {
            **config.TASK_CONFIGS,
            "T2I": {**config.TASK_CONFIGS["T2I"], "result_root": self.configured_root},
        }
        self.patches = [
            patch.object(storage, "RESULT_DIR", self.result_root),
            patch.object(config, "TASK_CONFIGS", self.task_configs),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temp_dir.cleanup()

    def make_image(self, *parts: str):
        path = os.path.join(*parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as image:
            image.write(b"image")

    def test_reads_versions_scenes_paths_and_urls_from_coexisting_roots(self):
        self.make_image(self.result_root, "legacy-only", "legacy-scene", "legacy.png")
        self.make_image(self.result_root, "shared", "legacy-scene", "legacy.png")
        self.make_image(self.result_root, "shared", "overlap-scene", "legacy.png")
        self.make_image(self.configured_root, "shared", "configured-scene", "configured.png")
        self.make_image(self.configured_root, "shared", "overlap-scene", "configured.png")
        self.make_image(self.configured_root, "configured-only", "configured-scene", "configured.png")

        self.assertEqual(
            storage.get_versions_for_type("T2I"),
            ["configured-only", "legacy-only", "shared"],
        )
        self.assertEqual(storage.get_common_scenes("T2I", "legacy-only", "shared"), ["legacy-scene"])
        self.assertEqual(
            storage.get_scene_path("T2I", "legacy-only", "legacy-scene"),
            os.path.join(self.result_root, "legacy-only", "legacy-scene"),
        )
        self.assertEqual(
            storage.get_scene_path("T2I", "shared", "legacy-scene"),
            os.path.join(self.result_root, "shared", "legacy-scene"),
        )
        self.assertEqual(
            storage.get_scene_path("T2I", "shared", "configured-scene"),
            os.path.join(self.configured_root, "shared", "configured-scene"),
        )
        self.assertEqual(
            storage.get_scene_path("T2I", "shared", "overlap-scene"),
            os.path.join(self.configured_root, "shared", "overlap-scene"),
        )
        self.assertEqual(storage.list_scene_files("T2I", "legacy-only", "legacy-scene"), ["legacy.png"])
        self.assertEqual(
            storage.get_result_image_url("T2I", "legacy-only", "legacy-scene", "legacy.png"),
            "/images/legacy-only/legacy-scene/legacy.png",
        )
        self.assertEqual(
            storage.get_result_image_url("T2I", "shared", "configured-scene", "configured.png"),
            "/images/T2I/shared/configured-scene/configured.png",
        )
        self.assertEqual(
            storage.get_result_image_url("T2I", "shared", "overlap-scene", "configured.png"),
            "/images/T2I/shared/overlap-scene/configured.png",
        )

    def test_t2i_versions_exclude_sibling_task_type_directories(self):
        self.make_image(self.configured_root, "model-a", "open", "scene.png")
        self.make_image(self.result_root, "TI2I", "model-d", "open", "scene.png")

        self.assertEqual(storage.get_versions_for_type("T2I"), ["model-a"])

    def test_new_result_uploads_write_only_to_configured_root(self):
        upload = SimpleNamespace(file=io.BytesIO(image_zip("img_001.png")))
        with patch.object(
            storage,
            "validate_result_zip",
            return_value={"status": "exact", "rename_map": {}, "image_count": 1},
        ):
            storage.upload_result_zip("T2I", "new", "model", "version", "new-scene", upload)

        self.assertTrue(os.path.exists(os.path.join(self.configured_root, "new_model_version", "new-scene", "img_001.png")))
        self.assertFalse(os.path.exists(os.path.join(self.result_root, "new_model_version", "new-scene", "img_001.png")))


class UploadValidationTests(unittest.TestCase):
    def test_unsafe_scene_and_version_are_rejected_before_upload_writes(self):
        prompt_upload = SimpleNamespace(file=io.BytesIO(b"img_001\tprompt\n"))
        result_upload = SimpleNamespace(file=io.BytesIO(image_zip("img_001.png")))

        with tempfile.TemporaryDirectory() as temp_dir:
            task_configs = {
                **config.TASK_CONFIGS,
                "T2I": {
                    **config.TASK_CONFIGS["T2I"],
                    "prompt_root": os.path.join(temp_dir, "prompt", "T2I"),
                    "result_root": os.path.join(temp_dir, "results", "T2I"),
                },
            }
            with patch.object(config, "TASK_CONFIGS", task_configs):
                with self.assertRaises(AppError):
                    storage.upload_dataset("T2I", "../escape", prompt_upload)
                with patch.object(
                    storage,
                    "validate_result_zip",
                    return_value={"status": "exact", "rename_map": {}, "image_count": 1},
                ):
                    with self.assertRaises(AppError):
                        storage.upload_result_zip("T2I", "../escape", "model", "v1", "scene", result_upload)

    def test_storage_component_validator_rejects_all_unsafe_leaf_values(self):
        for value in ("", "   ", ".", "..", "/absolute", "nested/path", "nested\\path"):
            with self.subTest(value=value):
                with self.assertRaises(AppError):
                    storage.validate_storage_component(value, "场景")


class ZipValidationTests(unittest.TestCase):
    def test_exact_name_validation_rejects_duplicate_stems(self):
        with self.assertRaises(AppError):
            storage.validate_image_zip_against_ids(
                image_zip("img_001.png", "img_001.jpg"),
                ["img_001"],
                "结果图",
            )


class ReferenceUploadValidationTests(unittest.TestCase):
    def test_upload_ref_rejects_duplicate_stems_against_scene_prompt_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_root = os.path.join(temp_dir, "prompt", "T2I")
            ref_root = os.path.join(temp_dir, "ref_images", "T2I")
            os.makedirs(prompt_root)
            os.makedirs(ref_root)
            existing_scene = os.path.join(ref_root, "scene")
            os.makedirs(existing_scene)
            with open(os.path.join(existing_scene, "existing.png"), "wb") as existing_file:
                existing_file.write(b"existing")
            with open(os.path.join(prompt_root, "scene.txt"), "w", encoding="utf-8") as prompt_file:
                prompt_file.write("img_001\tprompt\n")

            task_configs = {
                **config.TASK_CONFIGS,
                "T2I": {
                    **config.TASK_CONFIGS["T2I"],
                    "prompt_root": prompt_root,
                    "ref_root": ref_root,
                },
            }
            upload = SimpleNamespace(
                file=io.BytesIO(image_zip("img_001.png", "img_001.jpg")),
                filename="reference.zip",
            )
            with patch.object(config, "TASK_CONFIGS", task_configs):
                with self.assertRaises(AppError):
                    asyncio.run(main.upload_ref("T2I", "scene", upload, admin={}))

            self.assertTrue(os.path.exists(os.path.join(existing_scene, "existing.png")))


class UploadRouteAuthorizationTests(unittest.TestCase):
    def test_all_upload_routes_require_admin(self):
        protected_paths = {"/api/upload_dataset", "/api/upload", "/api/upload_ref"}
        routes = {route.path: route for route in main.app.routes if route.path in protected_paths}

        self.assertEqual(set(routes), protected_paths)
        for path, route in routes.items():
            with self.subTest(path=path):
                self.assertIn(main.require_admin, [dependency.call for dependency in route.dependant.dependencies])
