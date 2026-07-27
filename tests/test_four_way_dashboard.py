import unittest

from app_core.dashboard_service import dimension_stats


class FourWayDashboardTests(unittest.TestCase):
    def test_dimension_stats_separates_ties_and_keeps_combined_count(self):
        rows = [
            {"eval_mode": "full", "overall": "A"},
            {"eval_mode": "full", "overall": "tie_bad"},
            {"eval_mode": "full", "overall": "tie_good"},
            {"eval_mode": "full", "overall": "B"},
            {"eval_mode": "full", "overall": "tie_good"},
        ]

        self.assertEqual(
            dimension_stats(rows, "overall", "A", "B"),
            {
                "total": 5,
                "v_a_wins": 1,
                "tie_bad_count": 1,
                "tie_good_count": 2,
                "tie_count": 3,
                "v_b_wins": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
