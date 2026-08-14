import json
import unittest
from unittest.mock import patch

from app_core.dashboard_service import (
    dashboard_overview,
    detail_results,
    dimension_stats,
    worker_stats,
)


def video_row(**overrides):
    row = {
        "task_type": "T2V",
        "eval_mode": "selected",
        "v_a": "A",
        "v_b": "B",
        "scene": "motion",
        "filename": "clip.mp4",
        "overall": None,
        "aesthetic": None,
        "logic": None,
        "consistency": None,
        "fidelity": None,
        "text_consistency": None,
        "structure_reasonableness": None,
        "motion_reasonableness": None,
        "dynamism": None,
        "physical_plausibility": None,
        "visual_quality": None,
        "image_consistency": None,
        "selected_dimensions": "[]",
        "worker": "admin",
        "timestamp": "2026-07-28T10:00:00+08:00",
        "duration_seconds": 4,
        "bad_case_tags_a": "[]",
        "bad_case_tags_b": "[]",
        "bad_case_categories_a": "[]",
        "bad_case_categories_b": "[]",
    }
    row.update(overrides)
    return row


class VideoDashboardAggregationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            video_row(filename="one.mp4", dynamism="A", selected_dimensions='["dynamism"]'),
            video_row(filename="two.mp4", overall="B", selected_dimensions='["overall"]'),
            video_row(
                filename="three.mp4",
                overall="tie_good",
                dynamism="tie_bad",
                selected_dimensions='["overall", "dynamism"]',
            ),
        ]

    def test_dimension_denominator_counts_only_non_null_scores(self):
        self.assertEqual(dimension_stats(self.rows, "overall", "A", "B")["total"], 2)
        self.assertEqual(dimension_stats(self.rows, "dynamism", "A", "B")["total"], 2)

    def test_overview_and_pair_dimensions_are_active_and_config_ordered(self):
        page = {
            "rows": self.rows,
            "page": 1,
            "page_size": 10,
            "total_pairs": 1,
            "total_pages": 1,
            "scenes": ["motion"],
        }
        with patch("app_core.dashboard_service.fetch_overview_page", return_value=page):
            overview = dashboard_overview("T2V")

        self.assertEqual([item["key"] for item in overview["dims"]], ["overall", "dynamism"])
        pair = overview["pairs"][0]
        self.assertEqual(pair["active_dims"], ["overall", "dynamism"])
        self.assertEqual(pair["scenes"][0]["active_dims"], ["overall", "dynamism"])
        self.assertEqual(set(pair["dims"]), {"overall", "dynamism"})

    def test_worker_stats_exposes_only_active_dimensions(self):
        with patch("app_core.dashboard_service.fetch_result_rows", return_value=self.rows):
            result = worker_stats("T2V", "A", "B")
        self.assertEqual(result[0]["active_dims"], ["overall", "dynamism"])
        self.assertNotIn("visual_quality", result[0])

    def test_detail_rows_include_selected_dimensions_and_video_scores(self):
        rows = [
            video_row(
                filename="three.mp4",
                overall="tie_good",
                structure_reasonableness="B",
                dynamism="tie_bad",
                selected_dimensions='["overall", "structure_reasonableness", "dynamism"]',
            )
        ]
        with patch("app_core.dashboard_service.fetch_result_rows", return_value=rows), patch(
            "app_core.dashboard_service.get_preview_prompt_text", return_value="prompt"
        ), patch("app_core.dashboard_service.get_ref_image_url", return_value=None):
            result = detail_results("T2V", "A", "B", "motion")

        detail = result[0]
        self.assertEqual(
            detail["selected_dimensions"],
            ["overall", "structure_reasonableness", "dynamism"],
        )
        self.assertEqual(detail["scores"]["overall"], "tie_good")
        self.assertEqual(detail["structure_reasonableness"], "B")
        self.assertEqual(detail["scores"]["structure_reasonableness"], "B")
        self.assertEqual(detail["scores"]["dynamism"], "tie_bad")
        self.assertIn("visual_quality", detail["scores"])


if __name__ == "__main__":
    unittest.main()
