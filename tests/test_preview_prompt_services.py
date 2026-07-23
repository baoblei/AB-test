import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_core.dashboard_service import bad_case_details, detail_results
from app_core.storage import MISSING_PROMPT_TEXT, get_prompt_text


def make_row():
    return {
        "eval_mode": "full",
        "scene": "portrait",
        "filename": "missing.png",
        "overall": "A",
        "aesthetic": "A",
        "logic": "A",
        "consistency": "A",
        "fidelity": None,
        "worker": "alice",
        "timestamp": "2026-07-15T12:00:00+08:00",
        "duration_seconds": 3,
        "bad_case_tags_a": '["模糊失焦"]',
        "bad_case_tags_b": "[]",
        "bad_case_categories_a": '["画质问题"]',
        "bad_case_categories_b": "[]",
    }


class PreviewPromptServiceTests(unittest.TestCase):
    def test_dashboard_detail_and_bad_case_payloads_normalize_real_missing_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_prompt_root = str(Path(temp_dir) / "missing-prompts")
            with patch("app_core.dashboard_service.fetch_result_rows", return_value=[make_row()]):
                with patch("app_core.dashboard_service.get_ref_image_url", return_value=None):
                    with patch("app_core.storage.get_prompt_root", return_value=missing_prompt_root):
                        with patch("app_core.storage.PROMPT_DIR", missing_prompt_root):
                            raw_prompt = get_prompt_text("T2I", "portrait", "missing.png")
                            detail = detail_results("T2I", "A", "B", "portrait")
                            bad_cases = bad_case_details("T2I", "A", "B", "portrait")

        self.assertEqual(raw_prompt, MISSING_PROMPT_TEXT)
        self.assertEqual(detail[0]["prompt"], "")
        self.assertEqual(bad_cases["results"][0]["prompt"], "")


if __name__ == "__main__":
    unittest.main()
