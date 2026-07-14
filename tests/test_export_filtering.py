import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_core.database import connect, init_db
from app_core.errors import AppError
from app_core.export_service import (
    canonical_models,
    filter_rows,
    get_export_options,
    preview_export,
)
from app_core.schemas import ExportRequest


def make_row(row_id, **overrides):
    row = {
        "id": row_id,
        "eval_mode": "full",
        "task_type": "T2I",
        "v_a": "A",
        "v_b": "B",
        "scene": "open",
        "filename": f"image-{row_id}.png",
        "overall": "tie",
        "aesthetic": "tie",
        "logic": "tie",
        "consistency": "tie",
        "fidelity": None,
        "worker": "alice",
        "timestamp": "2026-07-15T12:00:00+08:00",
        "duration_seconds": 5,
        "skipped": 0,
        "user_id": 1,
        "bad_case_tags_a": "[]",
        "bad_case_tags_b": "[]",
        "bad_case_categories_a": "[]",
        "bad_case_categories_b": "[]",
    }
    row.update(overrides)
    return row


class ExportFilteringTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            make_row(1, aesthetic="A"),
            make_row(2, eval_mode="overall", overall="A", aesthetic=None, logic=None, consistency=None),
            make_row(3, scene="indoor", worker="bob", overall="B", aesthetic="B"),
            make_row(4, aesthetic=None),
        ]

    def test_dimension_filter_excludes_overall_only_rows(self):
        request = ExportRequest(task_type="T2I", v1="A", v2="B", scenes=["open"], dimensions=["aesthetic"])

        self.assertEqual([row["id"] for row in filter_rows(self.rows, request, "aesthetic")], [1])

    def test_result_filter_is_applied_per_sheet(self):
        request = ExportRequest(
            task_type="T2I", v1="A", v2="B", scenes=["open"], dimensions=["aesthetic"], result_filter="a"
        )

        self.assertEqual([row["id"] for row in filter_rows(self.rows, request, "overall")], [2])
        self.assertEqual([row["id"] for row in filter_rows(self.rows, request, "aesthetic")], [1])

    def test_filter_rows_enforces_base_row_invariants_for_mixed_input(self):
        rows = [
            make_row(1),
            make_row(2, task_type="TI2I"),
            make_row(3, v_a="A", v_b="C"),
            make_row(4, v_a="B", v_b="A"),
            make_row(5, skipped=1),
        ]
        request = ExportRequest(task_type="t2i", v1="B", v2="A")

        self.assertEqual([row["id"] for row in filter_rows(rows, request, "overall")], [1])

    def test_worker_time_mode_and_bad_case_filters_combine(self):
        rows = [
            make_row(
                1,
                task_type="TI2I",
                v_a="D",
                v_b="E",
                scene="portrait",
                fidelity="D",
                timestamp="2026-07-15T12:00:00+08:00",
                bad_case_tags_a='["模糊失焦"]',
            ),
            make_row(
                2,
                task_type="TI2I",
                v_a="D",
                v_b="E",
                scene="portrait",
                fidelity="D",
                worker="bob",
                timestamp="2026-07-15T12:00:00+08:00",
                bad_case_tags_a='["模糊失焦"]',
            ),
            make_row(
                3,
                task_type="TI2I",
                v_a="D",
                v_b="E",
                scene="portrait",
                fidelity="D",
                timestamp="2026-07-16T12:00:00+08:00",
                bad_case_tags_a='["模糊失焦"]',
            ),
            make_row(
                4,
                task_type="TI2I",
                v_a="D",
                v_b="E",
                scene="portrait",
                fidelity="D",
                timestamp="2026-07-15T12:00:00+08:00",
            ),
        ]
        request = ExportRequest(
            task_type="TI2I",
            v1="D",
            v2="E",
            scenes=["portrait"],
            workers=["alice"],
            dimensions=["fidelity"],
            start_time="2026-07-15T00:00:00+08:00",
            end_time="2026-07-15T23:59:59+08:00",
            eval_modes=["full"],
            bad_case_filter="with",
        )

        self.assertEqual(len(filter_rows(rows, request, "fidelity")), 1)

    def test_empty_dimensions_keeps_overall_only_and_preview_unions_selected_rows(self):
        request = ExportRequest(task_type="T2I", v1="B", v2="A")

        self.assertEqual(canonical_models(request), ("A", "B"))
        self.assertEqual([row["id"] for row in filter_rows(self.rows, request, "overall")], [1, 2, 3, 4])

    def test_validation_rejects_invalid_request_categories_with_chinese_messages(self):
        cases = [
            (ExportRequest(task_type="invalid", v1="A", v2="B"), "无效任务类型"),
            (ExportRequest(task_type="T2I", v1="", v2="B"), "模型名称不能为空"),
            (ExportRequest(task_type="T2I", v1="A", v2="A"), "模型必须不同"),
            (ExportRequest(task_type="T2I", v1="A", v2="B", dimensions=["fidelity"]), "无效导出维度"),
            (ExportRequest(task_type="T2I", v1="A", v2="B", result_filter="winner"), "无效结果筛选"),
            (ExportRequest(task_type="T2I", v1="A", v2="B", bad_case_filter="yes"), "无效坏例筛选"),
            (ExportRequest(task_type="T2I", v1="A", v2="B", eval_modes=["quick"]), "无效评测模式"),
            (
                ExportRequest(task_type="T2I", v1="A", v2="B", start_time="2026-07-15T00:00:00Z"),
                "导出时间必须为北京时间 ISO 格式",
            ),
            (
                ExportRequest(
                    task_type="T2I",
                    v1="A",
                    v2="B",
                    start_time="2026-07-16T00:00:00+08:00",
                    end_time="2026-07-15T00:00:00+08:00",
                ),
                "开始时间不能晚于结束时间",
            ),
        ]

        for request, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(AppError, message):
                    filter_rows(self.rows, request, "overall")


class ExportQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "export.db")
        self.db_path_patch = patch("app_core.database.DB_PATH", self.db_path)
        self.db_path_patch.start()
        init_db()
        self.insert_rows()

    def tearDown(self):
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def insert_rows(self):
        rows = [
            make_row(1, scene="zoo", filename="shared.png", timestamp="2026-07-15T09:00:00+08:00", aesthetic="A"),
            make_row(2, eval_mode="overall", scene="zoo", filename="overall.png", worker="zoe", timestamp="2026-07-15T10:00:00+08:00", overall="B", aesthetic=None, logic=None, consistency=None),
            make_row(3, scene="arch", filename="shared.png", worker="bob", timestamp="2026-07-15T11:00:00+08:00", aesthetic="B"),
            make_row(4, task_type="TI2I", v_a="A", v_b="B", scene="other", filename="other.png"),
            make_row(5, skipped=1, scene="skip", filename="skip.png"),
        ]
        conn = connect()
        columns = list(rows[0])
        placeholders = ", ".join("?" for _ in columns)
        conn.executemany(
            f"INSERT INTO results_log ({', '.join(columns)}) VALUES ({placeholders})",
            [tuple(row[column] for column in columns) for row in rows],
        )
        conn.commit()
        conn.close()

    def test_get_export_options_uses_canonical_pair_and_base_rows(self):
        options = get_export_options("T2I", "B", "A")

        self.assertEqual(options["v_a"], "A")
        self.assertEqual(options["v_b"], "B")
        self.assertEqual(options["scenes"], ["arch", "zoo"])
        self.assertEqual(options["workers"], ["alice", "bob", "zoe"])
        self.assertEqual([item["key"] for item in options["dimensions"]], ["aesthetic", "logic", "consistency"])
        self.assertEqual(options["min_time"], "2026-07-15T09:00:00+08:00")
        self.assertEqual(options["max_time"], "2026-07-15T11:00:00+08:00")
        self.assertEqual(options["total"], 3)

    def test_preview_includes_overall_and_counts_unique_images_across_sheets(self):
        request = ExportRequest(task_type="T2I", v1="B", v2="A", dimensions=["aesthetic"])

        self.assertEqual(
            preview_export(request),
            {"overall": 3, "dimensions": {"aesthetic": 2}, "unique_images": 3},
        )

    def test_preview_with_empty_dimensions_is_overall_only(self):
        request = ExportRequest(task_type="T2I", v1="A", v2="B", dimensions=[])

        self.assertEqual(preview_export(request), {"overall": 3, "dimensions": {}, "unique_images": 3})


if __name__ == "__main__":
    unittest.main()
