import unittest

from app_core.dashboard_service import dimension_stats


class FourWayDashboardTests(unittest.TestCase):
    def test_dimension_stats_separates_ties_and_keeps_combined_count(self):
        values = ["A", "tie_bad", "tie_good", "B", "tie_good"]
        rows = [
            {
                "eval_mode": "full",
                "task_type": "T2I",
                "v_a": "A",
                "v_b": "B",
                "scene": "scene",
                "filename": f"{index}.png",
                "worker": f"worker-{index}",
                "user_id": index,
                "overall": value,
            }
            for index, value in enumerate(values)
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
                "sample_count": 5,
                "intersection_sample_count": 0,
                "conflict_sample_count": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
