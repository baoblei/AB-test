import os
import shutil
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import main
from app_core import config, storage
from app_core import dataset_download_service
from app_core.dataset_download_service import (
    DatasetArtifact,
    create_dataset_artifact,
    list_datasets,
)
from app_core.errors import AppError


class DatasetDownloadRouteTests(unittest.TestCase):
    def test_routes_require_login(self):
        protected = {"/api/datasets", "/api/datasets/download"}
        routes = {
            route.path: route for route in main.app.routes if route.path in protected
        }
        self.assertEqual(set(routes), protected)
        for route in routes.values():
            self.assertIn(
                main.require_login,
                [dependency.call for dependency in route.dependant.dependencies],
            )

    def test_list_route_returns_service_payload(self):
        payload = [{"scene": "open", "prompt_count": 2}]
        with patch.object(main, "list_datasets", return_value=payload) as service:
            self.assertEqual(main.dataset_list("T2I", user={}), payload)
        service.assert_called_once_with("T2I")

    def test_download_route_builds_file_response_and_cleans_every_artifact(self):
        txt = DatasetArtifact("/tmp/open.txt", "open.txt", "text/plain; charset=utf-8", "/tmp/txt")
        zip_artifact = DatasetArtifact(
            "/tmp/edit.zip", "edit.zip", "application/zip", "/tmp/archive"
        )
        with patch.object(
            main, "create_dataset_artifact", side_effect=[txt, zip_artifact]
        ):
            txt_response = main.download_dataset("T2I", "open", False, user={})
            zip_response = main.download_dataset("TI2I", "edit", True, user={})
        self.assertIsNotNone(txt_response.background)
        self.assertIsNotNone(zip_response.background)
        self.assertEqual(txt_response.filename, "open.txt")
        self.assertEqual(zip_response.filename, "edit.zip")
        self.assertEqual(txt_response.media_type, "text/plain; charset=utf-8")
        self.assertEqual(zip_response.media_type, "application/zip")

    def test_download_route_background_removes_txt_snapshot(self):
        with tempfile.TemporaryDirectory() as parent:
            cleanup = Path(parent) / "snapshot"
            cleanup.mkdir()
            path = cleanup / "open.txt"
            path.write_bytes(b"prompt")
            artifact = DatasetArtifact(str(path), "open.txt", "text/plain; charset=utf-8", str(cleanup))
            with patch.object(main, "create_dataset_artifact", return_value=artifact):
                response = main.download_dataset("T2I", "open", False, user={})
            import asyncio
            asyncio.run(response.background())
            self.assertFalse(cleanup.exists())


class DatasetRoots:
    def __init__(self, root: Path):
        self.legacy_prompt_root = root / "prompt"
        self.prompt_roots = {
            task_type: self.legacy_prompt_root / task_type for task_type in ("T2I", "TI2I")
        }
        self.ref_roots = {
            task_type: root / "ref_images" / task_type for task_type in ("T2I", "TI2I")
        }

    def write_legacy_prompt(self, scene: str, content: str) -> None:
        self.legacy_prompt_root.mkdir(parents=True, exist_ok=True)
        (self.legacy_prompt_root / f"{scene}.txt").write_text(content, encoding="utf-8")

    def write_prompt(self, task_type: str, scene: str, content: str) -> None:
        root = self.prompt_roots[task_type]
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{scene}.txt").write_text(content, encoding="utf-8")

    def write_ref(self, task_type: str, scene: str, filename: str, data: bytes = b"image") -> None:
        root = self.ref_roots[task_type] / scene
        root.mkdir(parents=True, exist_ok=True)
        (root / filename).write_bytes(data)


@contextmanager
def configured_dataset_roots():
    with tempfile.TemporaryDirectory() as temp_dir:
        roots = DatasetRoots(Path(temp_dir).resolve())
        task_configs = {
            **config.TASK_CONFIGS,
            **{
                task_type: {
                    **config.TASK_CONFIGS[task_type],
                    "prompt_root": str(roots.prompt_roots[task_type]),
                    "ref_root": str(roots.ref_roots[task_type]),
                }
                for task_type in ("T2I", "TI2I")
            },
        }
        for root in (*roots.prompt_roots.values(), *roots.ref_roots.values()):
            root.mkdir(parents=True, exist_ok=True)
        with (
            patch.object(config, "TASK_CONFIGS", task_configs),
            patch.object(storage, "PROMPT_DIR", str(roots.legacy_prompt_root)),
            patch.object(storage, "REF_IMAGE_DIR", str(Path(temp_dir) / "ref_images")),
        ):
            yield roots


class DatasetMetadataTests(unittest.TestCase):
    def test_missing_secure_open_flag_fails_closed_before_storage_access(self):
        entry_points = (
            (list_datasets, ("T2I",)),
            (create_dataset_artifact, ("T2I", "open")),
        )
        for entry_point, arguments in entry_points:
            with (
                self.subTest(entry_point=entry_point.__name__),
                patch.object(dataset_download_service.os, "O_NOFOLLOW", None),
                patch.object(
                    dataset_download_service,
                    "get_dataset_scenes",
                    side_effect=AssertionError("storage must not be accessed"),
                ),
                patch.object(
                    config,
                    "get_task_config",
                    side_effect=AssertionError("storage must not be accessed"),
                ),
            ):
                with self.assertRaisesRegex(AppError, "平台.*安全"):
                    entry_point(*arguments)

    def test_lists_scenes_with_prompt_counts(self):
        with configured_dataset_roots() as roots:
            roots.write_prompt("T2I", "portrait", "a\tone\nb\ttwo\n")
            self.assertEqual(list_datasets("T2I"), [{"scene": "portrait", "prompt_count": 2}])

    def test_lists_task_specific_and_legacy_root_prompts(self):
        with configured_dataset_roots() as roots:
            roots.write_prompt("T2I", "portrait", "a\tone\n")
            roots.write_legacy_prompt("legacy", "a\tone\nb\ttwo\n")
            self.assertEqual(
                list_datasets("T2I"),
                [
                    {"scene": "legacy", "prompt_count": 2},
                    {"scene": "portrait", "prompt_count": 1},
                ],
            )

    def test_legacy_prompt_creates_immutable_txt_artifact(self):
        with configured_dataset_roots() as roots:
            roots.write_legacy_prompt("legacy", "a\tone\n")
            artifact = create_dataset_artifact("T2I", "legacy")
            self.addCleanup(shutil.rmtree, artifact.cleanup_dir, True)
            roots.write_legacy_prompt("legacy", "b\tchanged\n")
            self.assertEqual(artifact.filename, "legacy.txt")
            self.assertEqual(Path(artifact.path).read_bytes(), b"a\tone\n")

    def test_task_specific_prompt_wins_over_duplicate_legacy_scene(self):
        with configured_dataset_roots() as roots:
            roots.write_prompt("T2I", "duplicate", "a\ttask-specific\n")
            roots.write_legacy_prompt("duplicate", "a\tlegacy\nb\tlegacy\n")
            self.assertEqual(
                list_datasets("T2I"),
                [{"scene": "duplicate", "prompt_count": 1}],
            )
            artifact = create_dataset_artifact("T2I", "duplicate")
            self.addCleanup(shutil.rmtree, artifact.cleanup_dir, True)
            self.assertEqual(Path(artifact.path).read_bytes(), b"a\ttask-specific\n")

    def test_unsafe_task_specific_root_does_not_fall_back_to_legacy(self):
        with configured_dataset_roots() as roots:
            roots.write_legacy_prompt("open", "a\tlegacy\n")
            shutil.rmtree(roots.prompt_roots["T2I"])
            roots.prompt_roots["T2I"].write_bytes(b"not a directory")
            with self.assertRaisesRegex(AppError, "不安全"):
                create_dataset_artifact("T2I", "open")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unsupported")
    def test_unsafe_task_specific_prompt_file_does_not_fall_back_to_legacy(self):
        with configured_dataset_roots() as roots, tempfile.TemporaryDirectory() as outside:
            roots.write_legacy_prompt("open", "a\tlegacy\n")
            target = Path(outside) / "secret.txt"
            target.write_bytes(b"secret")
            os.symlink(target, roots.prompt_roots["T2I"] / "open.txt")
            with self.assertRaisesRegex(AppError, "不安全"):
                create_dataset_artifact("T2I", "open")

    def test_t2i_and_prompt_only_ti2i_return_txt_artifacts(self):
        with configured_dataset_roots() as roots:
            roots.write_prompt("T2I", "open", "a\tone\n")
            roots.write_prompt("TI2I", "edit", "b\ttwo\n")
            t2i = create_dataset_artifact("T2I", "open")
            ti2i = create_dataset_artifact("TI2I", "edit", include_ref=False)
            self.assertEqual(Path(t2i.path).read_bytes(), b"a\tone\n")
            self.assertEqual(t2i.filename, "open.txt")
            self.assertEqual(ti2i.filename, "edit.txt")
            self.assertTrue(t2i.cleanup_dir)
            self.assertTrue(ti2i.cleanup_dir)
            self.addCleanup(shutil.rmtree, t2i.cleanup_dir, True)
            self.addCleanup(shutil.rmtree, ti2i.cleanup_dir, True)

    def test_prompt_only_artifact_is_immutable_after_source_mutation(self):
        with configured_dataset_roots() as roots:
            roots.write_prompt("T2I", "open", "a\tone\n")
            artifact = create_dataset_artifact("T2I", "open")
            self.addCleanup(shutil.rmtree, artifact.cleanup_dir, True)
            roots.write_prompt("T2I", "open", "b\tchanged\n")
            self.assertEqual(Path(artifact.path).read_bytes(), b"a\tone\n")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unsupported")
    def test_prompt_file_symlink_is_rejected(self):
        with configured_dataset_roots() as roots, tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "secret.txt"
            target.write_bytes(b"secret")
            os.symlink(target, roots.prompt_roots["T2I"] / "open.txt")
            with self.assertRaisesRegex(AppError, "不安全"):
                create_dataset_artifact("T2I", "open")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unsupported")
    def test_prompt_root_symlink_is_rejected(self):
        with configured_dataset_roots() as roots, tempfile.TemporaryDirectory() as outside:
            shutil.rmtree(roots.prompt_roots["T2I"])
            Path(outside, "open.txt").write_bytes(b"secret")
            os.symlink(outside, roots.prompt_roots["T2I"])
            with self.assertRaisesRegex(AppError, "不安全"):
                create_dataset_artifact("T2I", "open")

    def test_prompt_replacement_between_stat_and_open_is_rejected(self):
        with configured_dataset_roots() as roots:
            roots.write_prompt("T2I", "open", "a\tone\n")
            prompt_path = roots.prompt_roots["T2I"] / "open.txt"
            real_open = os.open
            replaced = False

            def replace_after_stat(path, flags, *args, **kwargs):
                nonlocal replaced
                if path == "open.txt" and kwargs.get("dir_fd") is not None and not replaced:
                    replaced = True
                    prompt_path.unlink()
                    prompt_path.write_bytes(b"secret")
                return real_open(path, flags, *args, **kwargs)

            with patch("app_core.dataset_download_service.os.open", side_effect=replace_after_stat):
                with self.assertRaisesRegex(AppError, "不安全"):
                    create_dataset_artifact("T2I", "open")

    def test_rejects_unsafe_or_missing_scene_before_reading(self):
        with configured_dataset_roots():
            with self.assertRaisesRegex(AppError, "场景必须是有效的目录名"):
                create_dataset_artifact("T2I", "../secret")
            with self.assertRaisesRegex(AppError, "未找到场景 missing 的 prompt 文件"):
                create_dataset_artifact("T2I", "missing")


class DatasetReferenceArchiveTests(unittest.TestCase):
    def test_ti2i_reference_archive_contains_prompt_and_matching_images(self):
        with configured_dataset_roots() as roots:
            roots.write_prompt("TI2I", "edit", "a\tone\nb\ttwo\n")
            roots.write_ref("TI2I", "edit", "a.jpg", b"a-image")
            roots.write_ref("TI2I", "edit", "b.png", b"b-image")
            artifact = create_dataset_artifact("TI2I", "edit", include_ref=True)
            self.addCleanup(shutil.rmtree, artifact.cleanup_dir, True)
            with zipfile.ZipFile(artifact.path) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["edit.txt", "ref_images/a.jpg", "ref_images/b.png"],
                )
                self.assertEqual(archive.read("edit.txt"), b"a\tone\nb\ttwo\n")
            self.assertEqual(artifact.filename, "edit.zip")
            self.assertTrue(artifact.cleanup_dir)

    def test_reference_archive_rejects_missing_extra_and_duplicate_stems(self):
        cases = (
            ({"a.jpg": b"a"}, "缺少 1 个"),
            ({"a.jpg": b"a", "b.png": b"b", "extra.png": b"x"}, "多出 1 个"),
            ({"a.jpg": b"a", "a.png": b"a2", "b.png": b"b"}, "重复"),
        )
        for files, message in cases:
            with self.subTest(files=files), configured_dataset_roots() as roots:
                roots.write_prompt("TI2I", "edit", "a\tone\nb\ttwo\n")
                for name, data in files.items():
                    roots.write_ref("TI2I", "edit", name, data)
                with self.assertRaisesRegex(AppError, message):
                    create_dataset_artifact("TI2I", "edit", include_ref=True)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unsupported")
    def test_reference_archive_rejects_symlinked_image(self):
        with configured_dataset_roots() as roots, tempfile.TemporaryDirectory() as outside:
            roots.write_prompt("TI2I", "edit", "a\tone\n")
            outside_image = Path(outside) / "target.jpg"
            outside_image.write_bytes(b"outside-image")
            scene_root = roots.ref_roots["TI2I"] / "edit"
            scene_root.mkdir(parents=True, exist_ok=True)
            os.symlink(outside_image, scene_root / "a.jpg")
            with self.assertRaisesRegex(AppError, "不安全"):
                create_dataset_artifact("TI2I", "edit", include_ref=True)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unsupported")
    def test_reference_replacement_after_validation_does_not_change_archive(self):
        with configured_dataset_roots() as roots, tempfile.TemporaryDirectory() as outside:
            roots.write_prompt("TI2I", "edit", "a\tone\n")
            roots.write_ref("TI2I", "edit", "a.jpg", b"validated-image")
            ref_path = roots.ref_roots["TI2I"] / "edit" / "a.jpg"
            replacement = Path(outside) / "replacement.jpg"
            replacement.write_bytes(b"replacement-image")
            original_write = zipfile.ZipFile.write
            replaced = False

            def replace_before_write(archive, filename, *args, **kwargs):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    ref_path.unlink()
                    os.symlink(replacement, ref_path)
                return original_write(archive, filename, *args, **kwargs)

            with patch.object(zipfile.ZipFile, "write", replace_before_write):
                artifact = create_dataset_artifact("TI2I", "edit", include_ref=True)
            self.addCleanup(shutil.rmtree, artifact.cleanup_dir, True)
            with zipfile.ZipFile(artifact.path) as archive:
                self.assertEqual(archive.read("ref_images/a.jpg"), b"validated-image")

    def test_prompt_replacement_after_validation_does_not_change_archive(self):
        with configured_dataset_roots() as roots:
            roots.write_prompt("TI2I", "edit", "a\tone\n")
            roots.write_ref("TI2I", "edit", "a.jpg", b"a-image")
            prompt_path = roots.prompt_roots["TI2I"] / "edit.txt"
            original_write = zipfile.ZipFile.write
            replaced = False

            def replace_before_write(archive, filename, *args, **kwargs):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    prompt_path.write_text("b\tchanged\n", encoding="utf-8")
                return original_write(archive, filename, *args, **kwargs)

            with patch.object(zipfile.ZipFile, "write", replace_before_write):
                artifact = create_dataset_artifact("TI2I", "edit", include_ref=True)
            self.addCleanup(shutil.rmtree, artifact.cleanup_dir, True)
            with zipfile.ZipFile(artifact.path) as archive:
                self.assertEqual(archive.read("edit.txt"), b"a\tone\n")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unsupported")
    def test_reference_scene_directory_symlink_is_rejected(self):
        with configured_dataset_roots() as roots, tempfile.TemporaryDirectory() as outside:
            roots.write_prompt("TI2I", "edit", "a\tone\n")
            Path(outside, "a.jpg").write_bytes(b"outside")
            os.symlink(outside, roots.ref_roots["TI2I"] / "edit")
            with self.assertRaisesRegex(AppError, "不安全"):
                create_dataset_artifact("TI2I", "edit", include_ref=True)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unsupported")
    def test_reference_scene_replacement_before_open_is_rejected(self):
        with configured_dataset_roots() as roots, tempfile.TemporaryDirectory() as outside:
            roots.write_prompt("TI2I", "edit", "a\tone\n")
            roots.write_ref("TI2I", "edit", "a.jpg", b"inside")
            Path(outside, "a.jpg").write_bytes(b"outside")
            scene_path = roots.ref_roots["TI2I"] / "edit"
            parked = roots.ref_roots["TI2I"] / "parked"
            real_open = os.open
            replaced = False

            def replace_before_scene_open(path, flags, *args, **kwargs):
                nonlocal replaced
                if path == "edit" and kwargs.get("dir_fd") is not None and not replaced:
                    replaced = True
                    scene_path.rename(parked)
                    os.symlink(outside, scene_path)
                return real_open(path, flags, *args, **kwargs)

            with patch("app_core.dataset_download_service.os.open", side_effect=replace_before_scene_open):
                with self.assertRaisesRegex(AppError, "不安全"):
                    create_dataset_artifact("TI2I", "edit", include_ref=True)


class RepositorySmokeDatasetTests(unittest.TestCase):
    def test_controlled_datasets_expose_three_six_prompt_scenes_per_task(self):
        self.assertEqual(
            list_datasets("T2I"),
            [
                {"scene": "portrait_anatomy", "prompt_count": 6},
                {"scene": "spatial_composition", "prompt_count": 6},
                {"scene": "text_product", "prompt_count": 6},
            ],
        )
        self.assertEqual(
            list_datasets("TI2I"),
            [
                {"scene": "appearance_edit", "prompt_count": 6},
                {"scene": "background_style", "prompt_count": 6},
                {"scene": "object_edit", "prompt_count": 6},
            ],
        )

    def test_prompt_only_artifacts_match_committed_prompt_bytes(self):
        cases = (
            ("T2I", "portrait_anatomy"),
            ("TI2I", "object_edit"),
        )
        for task, scene in cases:
            with self.subTest(task=task, scene=scene):
                prompt = Path(f"prompt/{task}/{scene}.txt").read_bytes()
                artifact = create_dataset_artifact(task, scene, include_ref=False)
                self.addCleanup(shutil.rmtree, artifact.cleanup_dir, True)
                self.assertEqual(Path(artifact.path).read_bytes(), prompt)

    def test_object_edit_reference_archive_has_deterministic_members(self):
        prompt = Path("prompt/TI2I/object_edit.txt")
        references = [
            Path(f"ref_images/TI2I/object_edit/object_edit_{index:02d}.jpg")
            for index in range(1, 7)
        ]

        artifact = create_dataset_artifact("TI2I", "object_edit", include_ref=True)
        self.addCleanup(shutil.rmtree, artifact.cleanup_dir, True)

        with zipfile.ZipFile(artifact.path) as archive:
            self.assertEqual(
                archive.namelist(),
                [
                    "object_edit.txt",
                    *(f"ref_images/{reference.name}" for reference in references),
                ],
            )
            self.assertEqual(archive.read("object_edit.txt"), prompt.read_bytes())
            for reference in references:
                self.assertEqual(
                    archive.read(f"ref_images/{reference.name}"),
                    reference.read_bytes(),
                )
