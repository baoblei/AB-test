import json
import subprocess
import unittest
from pathlib import Path

import imageio_ffmpeg

from app_core.storage import parse_prompt_file_bytes
from app_core.video_media import extract_first_frame_webp


class MockVideoDatasetTests(unittest.TestCase):
    def test_expected_models_prompts_references_and_videos_exist(self):
        t2v_ids = parse_prompt_file_bytes(
            Path("prompt/T2V/motion_basics.txt").read_bytes()
        )["ids"]
        ti2v_ids = parse_prompt_file_bytes(
            Path("prompt/TI2V/image_animation.txt").read_bytes()
        )["ids"]
        self.assertEqual(t2v_ids, ["motion_01", "motion_02", "motion_03"])
        self.assertEqual(
            ti2v_ids, ["animation_01", "animation_02", "animation_03"]
        )
        video_paths = list(
            Path("results/T2V").glob("test_*_default/motion_basics/*.mp4")
        )
        video_paths += list(
            Path("results/TI2V").glob("test_*_default/image_animation/*.mp4")
        )
        refs = list(Path("ref_images/TI2V/image_animation").glob("*.png"))
        self.assertEqual(len(video_paths), 12)
        self.assertEqual(len(refs), 3)
        self.assertTrue(all(path.stat().st_size > 0 for path in video_paths))

    def test_every_mock_video_has_expected_codec_geometry_rate_and_duration(self):
        videos = list(Path("results/T2V").rglob("*.mp4"))
        videos += list(Path("results/TI2V").rglob("*.mp4"))
        self.assertEqual(len(videos), 12)
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        for video in videos:
            with self.subTest(video=video):
                self.assertGreater(len(extract_first_frame_webp(str(video))), 100)
                probe = subprocess.run(
                    [ffmpeg, "-i", str(video), "-hide_banner"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                metadata = probe.stderr
                self.assertIn("Video: h264", metadata)
                self.assertIn("yuv420p", metadata)
                self.assertIn("640x360", metadata)
                self.assertIn("12 fps", metadata)
                self.assertIn("Duration: 00:00:04.00", metadata)
                self.assertNotIn("Audio:", metadata)

    def test_generator_check_mode_reports_all_assets_current(self):
        output = subprocess.check_output(
            ["python3", "scripts/generate_mock_video_dataset.py", "--check"],
            text=True,
        )
        report = json.loads(output)

        self.assertEqual(report["videos"], 12)
        self.assertEqual(report["references"], 3)
        self.assertEqual(report["missing"], [])


if __name__ == "__main__":
    unittest.main()
