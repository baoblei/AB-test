import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

import main
from app_core.errors import AppError, NotFoundError
from app_core import thumbnail_service


get_image_thumbnail = getattr(thumbnail_service, "get_image_thumbnail", None)


class ThumbnailServiceAvailabilityTests(unittest.TestCase):
    def test_thumbnail_service_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("app_core.thumbnail_service"))


class ThumbnailServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            get_image_thumbnail, "thumbnail service must expose get_image_thumbnail"
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "source.png"
        self.cache_root = self.root / "cache"
        Image.new("RGB", (2048, 1024), "navy").save(self.source)

    def tearDown(self):
        self.temp_dir.cleanup()

    def result_thumbnail(self):
        return get_image_thumbnail(
            "result",
            "T2I",
            "scene",
            "image.png",
            model="model-a",
            cache_root=self.cache_root,
        )

    def test_result_thumbnail_is_256_pixel_webp_with_preserved_aspect_ratio(self):
        with patch(
            "app_core.thumbnail_service.get_result_image_path",
            return_value=os.fspath(self.source),
        ):
            thumbnail = self.result_thumbnail()

        with Image.open(thumbnail) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (256, 128))

    def test_cached_thumbnail_is_reused_without_rewriting(self):
        with patch(
            "app_core.thumbnail_service.get_result_image_path",
            return_value=os.fspath(self.source),
        ):
            thumbnail = self.result_thumbnail()
            first_mtime = os.stat(thumbnail).st_mtime_ns
            cached = self.result_thumbnail()

        self.assertEqual(cached, thumbnail)
        self.assertEqual(os.stat(cached).st_mtime_ns, first_mtime)

    def test_source_change_uses_a_new_cache_file(self):
        with patch(
            "app_core.thumbnail_service.get_result_image_path",
            return_value=os.fspath(self.source),
        ):
            first = self.result_thumbnail()
            Image.new("RGB", (1024, 2048), "orange").save(self.source)
            stat = self.source.stat()
            os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            second = self.result_thumbnail()

        self.assertNotEqual(second, first)
        with Image.open(second) as image:
            self.assertEqual(image.size, (128, 256))

    def test_reference_thumbnail_uses_reference_resolver_without_model(self):
        with patch(
            "app_core.thumbnail_service.get_ref_image_path",
            return_value=os.fspath(self.source),
        ) as resolver:
            thumbnail = get_image_thumbnail(
                "ref",
                "TI2I",
                "scene",
                "image.png",
                cache_root=self.cache_root,
            )

        resolver.assert_called_once_with("TI2I", "scene", "image.png")
        self.assertTrue(Path(thumbnail).is_file())

    def test_invalid_kind_and_missing_result_model_are_rejected(self):
        with self.assertRaisesRegex(AppError, "无效的缩略图类型"):
            get_image_thumbnail(
                "other", "T2I", "scene", "image.png", cache_root=self.cache_root
            )
        with self.assertRaisesRegex(AppError, "结果图缩略图缺少模型"):
            get_image_thumbnail(
                "result", "T2I", "scene", "image.png", cache_root=self.cache_root
            )

    def test_missing_and_unsafe_sources_are_rejected(self):
        with patch(
            "app_core.thumbnail_service.get_result_image_path", return_value=None
        ):
            with self.assertRaisesRegex(NotFoundError, "图片不存在"):
                self.result_thumbnail()

        with self.assertRaises(AppError):
            get_image_thumbnail(
                "ref",
                "TI2I",
                "../scene",
                "image.png",
                cache_root=self.cache_root,
            )


class ThumbnailRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.thumbnail = Path(self.temp_dir.name) / "thumbnail.webp"
        Image.new("RGB", (32, 16), "green").save(self.thumbnail, format="WEBP")
        self.client = TestClient(main.app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_result_thumbnail_route_returns_webp_with_cache_header(self):
        with patch(
            "main.get_image_thumbnail",
            return_value=os.fspath(self.thumbnail),
            create=True,
        ) as service:
            response = self.client.get(
                "/api/image-thumbnail",
                params={
                    "kind": "result",
                    "task_type": "T2I",
                    "model": "model-a",
                    "scene": "scene",
                    "filename": "image.png",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/webp")
        self.assertEqual(response.headers["cache-control"], "public, max-age=3600")
        service.assert_called_once_with(
            "result", "T2I", "scene", "image.png", "model-a"
        )

    def test_reference_route_passes_no_model(self):
        with patch(
            "main.get_image_thumbnail",
            return_value=os.fspath(self.thumbnail),
            create=True,
        ) as service:
            response = self.client.get(
                "/api/image-thumbnail",
                params={
                    "kind": "ref",
                    "task_type": "TI2I",
                    "scene": "scene",
                    "filename": "image.png",
                },
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with("ref", "TI2I", "scene", "image.png", None)

    def test_result_route_rejects_missing_model(self):
        response = self.client.get(
            "/api/image-thumbnail",
            params={
                "kind": "result",
                "task_type": "T2I",
                "scene": "scene",
                "filename": "image.png",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "结果图缩略图缺少模型")


if __name__ == "__main__":
    unittest.main()
