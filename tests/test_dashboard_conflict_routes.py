import unittest
from unittest.mock import patch

import main


class DashboardConflictRouteTests(unittest.TestCase):
    @patch("main.dashboard_overview_service", return_value={})
    def test_overview_forwards_conflict_and_page_filters(self, service):
        main.dashboard_overview(
            "T2I",
            exclude_conflicts=True,
            conflict_tolerance=0.25,
            page=3,
            page_size=10,
            search_v1="alpha",
            search_v2="beta",
            scene="portrait",
            model_names='["model-a"]',
        )

        service.assert_called_once_with(
            "T2I",
            exclude_conflicts=True,
            conflict_tolerance=0.25,
            page=3,
            page_size=10,
            search_v1="alpha",
            search_v2="beta",
            scene="portrait",
            model_names=["model-a"],
        )

    @patch("main.worker_stats_service", return_value=[])
    def test_worker_forwards_conflict_settings(self, service):
        main.worker_stats(
            "T2I",
            "model-a",
            "model-b",
            "scene-1",
            exclude_conflicts=True,
            conflict_tolerance=0.3,
        )

        service.assert_called_once_with(
            "T2I",
            "model-a",
            "model-b",
            "scene-1",
            exclude_conflicts=True,
            conflict_tolerance=0.3,
        )

    @patch("main.worker_scope_stats_service", return_value={})
    def test_worker_scope_forwards_selected_evaluators(self, service):
        main.worker_scope_stats(
            "T2I",
            "model-a",
            "model-b",
            "scene-1",
            exclude_conflicts=True,
            conflict_tolerance=0.2,
            workers='["alice", "bob"]',
        )

        service.assert_called_once_with(
            "T2I",
            "model-a",
            "model-b",
            "scene-1",
            workers=["alice", "bob"],
            exclude_conflicts=True,
            conflict_tolerance=0.2,
        )

    @patch("main.detail_results_service", return_value=[])
    def test_detail_forwards_conflict_tolerance(self, service):
        main.detail_results(
            "T2I", "model-a", "model-b", "scene-1", conflict_tolerance=0.35
        )

        service.assert_called_once_with(
            "T2I", "model-a", "model-b", "scene-1", conflict_tolerance=0.35
        )

    @patch("main.ranking_service", return_value=[])
    def test_ranking_forwards_conflict_settings(self, service):
        main.ranking(
            "T2I",
            "scene-1",
            "overall",
            exclude_conflicts=True,
            conflict_tolerance=0.15,
        )

        service.assert_called_once_with(
            "T2I",
            "scene-1",
            "overall",
            exclude_conflicts=True,
            conflict_tolerance=0.15,
        )


if __name__ == "__main__":
    unittest.main()
