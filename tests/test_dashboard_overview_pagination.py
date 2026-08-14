import sqlite3
import unittest
from unittest.mock import patch

from app_core import dashboard_service


class DashboardOverviewPaginationTests(unittest.TestCase):
    def make_connection(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE results_log (
                task_type TEXT NOT NULL,
                skipped INTEGER NOT NULL,
                v_a TEXT NOT NULL,
                v_b TEXT NOT NULL,
                scene TEXT NOT NULL,
                filename TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT INTO results_log VALUES ('T2I', 0, ?, ?, ?, ?, '2026-08-14T10:00:00+08:00')",
            [
                (
                    f"model-{index:02d}-a",
                    f"model-{index:02d}-b",
                    f"scene-{index % 3}",
                    f"{index}.png",
                )
                for index in range(25)
            ],
        )
        return conn

    def test_pair_page_query_reads_only_ten_current_pair_rows(self):
        conn = self.make_connection()
        with patch("app_core.dashboard_service.connect", return_value=conn):
            page = dashboard_service.fetch_overview_page(
                "T2I", page=2, page_size=10
            )

        self.assertEqual(page["page"], 2)
        self.assertEqual(page["page_size"], 10)
        self.assertEqual(page["total_pairs"], 25)
        self.assertEqual(page["total_pages"], 3)
        self.assertEqual(len(page["rows"]), 10)
        self.assertEqual(page["rows"][0]["v_a"], "model-10-a")
        self.assertEqual(page["rows"][-1]["v_a"], "model-19-a")
        self.assertEqual(page["scenes"], ["scene-0", "scene-1", "scene-2"])

    def test_pair_page_filters_before_pagination_without_trimming_pair_rows(self):
        conn = self.make_connection()
        with patch("app_core.dashboard_service.connect", return_value=conn):
            page = dashboard_service.fetch_overview_page(
                "T2I",
                page=1,
                page_size=10,
                search_v1="03",
                scene="scene-0",
                model_names=["model-03-a"],
            )

        self.assertEqual(page["total_pairs"], 1)
        self.assertEqual([row["v_a"] for row in page["rows"]], ["model-03-a"])


if __name__ == "__main__":
    unittest.main()
