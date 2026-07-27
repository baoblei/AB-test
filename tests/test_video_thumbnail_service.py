import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app_core.errors import AppError
from app_core.thumbnail_service import get_image_thumbnail
from app_core.video_media import extract_first_frame_webp


def png_bytes(size=(640, 360)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, "purple").save(output, format="PNG")
    return output.getvalue()


class FirstFrameExtractionTests(unittest.TestCase):
    def test_ffmpeg_frame_is_resized_and_converted_to_webp(self):
        completed = SimpleNamespace(returncode=0, stdout=png_bytes(), stderr=b"")
        with patch(
            "app_core.video_media.imageio_ffmpeg.get_ffmpeg_exe",
            return_value="/managed/ffmpeg",
        ), patch("app_core.video_media.subprocess.run", return_value=completed) as run:
            result = extract_first_frame_webp("/tmp/clip.mp4", max_size=256)

        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (256, 144))
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/managed/ffmpeg")
        self.assertIn("pipe:1", command)

    def test_failed_or_empty_decode_is_rejected(self):
        for completed in (
            SimpleNamespace(returncode=1, stdout=b"", stderr=b"bad"),
            SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
        ):
            with self.subTest(returncode=completed.returncode), patch(
                "app_core.video_media.imageio_ffmpeg.get_ffmpeg_exe",
                return_value="ffmpeg",
            ), patch("app_core.video_media.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(AppError, "视频无法提取首帧"):
                    extract_first_frame_webp("clip.mp4")

    def test_missing_managed_ffmpeg_is_reported_as_video_error(self):
        with patch(
            "app_core.video_media.imageio_ffmpeg.get_ffmpeg_exe",
            side_effect=RuntimeError("missing"),
        ):
            with self.assertRaisesRegex(AppError, "视频无法提取首帧"):
                extract_first_frame_webp("clip.mp4")


class VideoThumbnailTests(unittest.TestCase):
    def test_video_result_thumbnail_uses_first_frame_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "clip.mp4"
            source.write_bytes(b"video")
            cache = Path(temp_dir) / "cache"
            expected = png_bytes((320, 180))
            with patch(
                "app_core.thumbnail_service.get_result_image_path",
                return_value=os.fspath(source),
            ), patch(
                "app_core.thumbnail_service.extract_first_frame_webp",
                return_value=expected,
                create=True,
            ) as extractor:
                thumbnail = get_image_thumbnail(
                    "result",
                    "T2V",
                    "motion",
                    "clip.mp4",
                    model="model-a",
                    cache_root=cache,
                )

            self.assertEqual(Path(thumbnail).read_bytes(), expected)
            extractor.assert_called_once_with(os.fspath(source), 256)


if __name__ == "__main__":
    unittest.main()
