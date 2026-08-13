import unittest
from unittest.mock import patch

import main


class DashboardConflictRouteTests(unittest.TestCase):
    @patch("main.dashboard_overview_service", return_value={})
    def test_overview_forwards_exclude_conflicts(self, service):
        main.dashboard_overview("T2I", exclude_conflicts=True)

        service.assert_called_once_with("T2I", exclude_conflicts=True)

    @patch("main.worker_stats_service", return_value=[])
    def test_worker_forwards_exclude_conflicts(self, service):
        main.worker_stats(
            "T2I", "model-a", "model-b", "scene-1", exclude_conflicts=True
        )

        service.assert_called_once_with(
            "T2I", "model-a", "model-b", "scene-1", exclude_conflicts=True
        )

    @patch("main.ranking_service", return_value=[])
    def test_ranking_forwards_exclude_conflicts(self, service):
        main.ranking("T2I", "scene-1", "overall", exclude_conflicts=True)

        service.assert_called_once_with(
            "T2I", "scene-1", "overall", exclude_conflicts=True
        )


if __name__ == "__main__":
    unittest.main()
