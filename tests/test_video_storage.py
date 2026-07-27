import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app_core import config, storage
from app_core.errors import AppError


def media_zip(name: str, payload: bytes = b"media") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, payload)
    return output.getvalue()


class VideoZipValidationTests(unittest.TestCase):
    def test_video_zip_accepts_configured_extensions(self):
        for filename in ("clip_01.mp4", "clip_01.webm"):
            with self.subTest(filename=filename), patch(
                "app_core.storage.get_prompt_ids", return_value=["clip_01"]
            ):
                validation = storage.validate_result_zip(
                    "T2V", "motion", media_zip(filename)
                )
            self.assertEqual(validation["media_count"], 1)
            self.assertNotIn("image_count", validation)

    def test_video_zip_rejects_image_and_image_zip_remains_compatible(self):
        with patch("app_core.storage.get_prompt_ids", return_value=["clip_01"]):
            with self.assertRaisesRegex(AppError, "视频"):
                storage.validate_result_zip(
                    "T2V", "motion", media_zip("clip_01.png")
                )

            validation = storage.validate_result_zip(
                "T2I", "portrait", media_zip("clip_01.png")
            )
        self.assertEqual(validation["image_count"], 1)

    def test_scene_file_listing_uses_task_result_extensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scene = Path(temp_dir)
            for name in ("a.mp4", "b.webm", "ignored.png"):
                (scene / name).write_bytes(b"x")
            with patch("app_core.storage.get_scene_path", return_value=temp_dir):
                self.assertEqual(
                    storage.list_scene_files("T2V", "model", "scene"),
                    ["a.mp4", "b.webm"],
                )


class StagedVideoUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.result_root = self.root / "results" / "T2V"
        self.scene_path = (
            self.result_root / "test_Nova_default" / "motion"
        )
        self.scene_path.mkdir(parents=True)
        (self.scene_path / "old.mp4").write_bytes(b"old")
        self.task_configs = {
            **config.TASK_CONFIGS,
            "T2V": {
                **config.TASK_CONFIGS["T2V"],
                "result_root": os.fspath(self.result_root),
            },
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def upload(self):
        return SimpleNamespace(file=io.BytesIO(media_zip("clip_01.mp4", b"new")))

    def test_decode_failure_preserves_existing_scene(self):
        with patch.object(config, "TASK_CONFIGS", self.task_configs), patch(
            "app_core.storage.get_prompt_ids", return_value=["clip_01"]
        ), patch(
            "app_core.storage.extract_first_frame_webp",
            side_effect=AppError("视频无法提取首帧"),
            create=True,
        ):
            with self.assertRaisesRegex(AppError, "视频无法提取首帧"):
                storage.upload_result_zip(
                    "T2V", "test", "Nova", "default", "motion", self.upload()
                )

        self.assertEqual((self.scene_path / "old.mp4").read_bytes(), b"old")
        self.assertFalse((self.scene_path / "clip_01.mp4").exists())

    def test_success_replaces_scene_after_decode_and_warms_thumbnail(self):
        with patch.object(config, "TASK_CONFIGS", self.task_configs), patch(
            "app_core.storage.get_prompt_ids", return_value=["clip_01"]
        ), patch(
            "app_core.storage.extract_first_frame_webp", return_value=b"poster", create=True
        ) as decoder, patch(
            "app_core.thumbnail_service.warm_result_thumbnail", create=True
        ) as warmer:
            result = storage.upload_result_zip(
                "T2V", "test", "Nova", "default", "motion", self.upload()
            )

        self.assertEqual(result["media_count"], 1)
        self.assertEqual((self.scene_path / "clip_01.mp4").read_bytes(), b"new")
        self.assertFalse((self.scene_path / "old.mp4").exists())
        decoder.assert_called_once()
        warmer.assert_called_once_with(
            "T2V", "test_Nova_default", "motion", "clip_01.mp4"
        )


if __name__ == "__main__":
    unittest.main()
