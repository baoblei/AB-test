from io import BytesIO
import unittest
from unittest.mock import patch

from openpyxl import load_workbook

from app_core.export_service import build_workbook, workbook_bytes
from app_core.schemas import ExportRequest


def make_row(row_id, **overrides):
    row = {
        "id": row_id,
        "eval_mode": "full",
        "task_type": "T2I",
        "v_a": "A",
        "v_b": "B",
        "scene": "city",
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


class ExportWorkbookTests(unittest.TestCase):
    def setUp(self):
        self.t2i_request = ExportRequest(
            task_type="T2I",
            v1="B",
            v2="A",
            scenes=["city", "zoo"],
            dimensions=["consistency", "aesthetic"],
            workers=["alice"],
            start_time="2026-07-15T00:00:00+08:00",
            end_time="2026-07-15T23:59:59+08:00",
            eval_modes=["full", "overall"],
            result_filter="a",
            bad_case_filter="all",
            include_images=False,
            include_bad_cases=True,
            include_duration=True,
        )
        self.t2i_rows = [
            make_row(1, scene="zoo", overall="tie", aesthetic="A", consistency="B", bad_case_tags_a='["模糊失焦"]'),
            make_row(2, eval_mode="overall", scene="city", overall="A", aesthetic=None, logic=None, consistency=None),
            make_row(3, scene="city", overall="B", aesthetic="B", consistency="A", worker="bob"),
            make_row(4, scene="city", overall="A", aesthetic="A", consistency="A", skipped=1),
        ]
        self.ti2i_request = ExportRequest(
            task_type="TI2I", v1="D", v2="E", dimensions=["fidelity"], include_bad_cases=False, include_duration=False
        )
        self.ti2i_rows = [
            make_row(1, task_type="TI2I", v_a="D", v_b="E", scene="portrait", fidelity="D")
        ]

    @patch("app_core.export_service.get_prompt_text", return_value="a red car")
    def test_t2i_workbook_has_overall_config_ordered_sheets_and_metadata(self, _prompt):
        workbook = build_workbook(
            self.t2i_request, self.t2i_rows, generated_at="2026-07-15T10:00:00+08:00"
        )

        self.assertEqual(workbook.sheetnames, ["Overall", "美学明细", "一致性明细"])
        overall = workbook["Overall"]
        self.assertEqual(overall["A1"].value, "评测结果导出")
        self.assertEqual(overall["B2"].value, "2026-07-15T10:00:00+08:00")
        self.assertEqual(overall["B3"].value, "T2I")
        self.assertEqual(overall["B4"].value, "A vs B")
        self.assertIn("city, zoo", [cell.value for row in overall.iter_rows(min_row=1, max_row=9) for cell in row])
        self.assertIn("一致性, 美学", [cell.value for row in overall.iter_rows(min_row=1, max_row=9) for cell in row])
        self.assertEqual(overall["A12"].value, "全部场景")

    @patch("app_core.export_service.get_prompt_text", return_value="a red car")
    def test_overall_and_detail_apply_result_filter_independently(self, _prompt):
        workbook = build_workbook(self.t2i_request, self.t2i_rows)
        overall = workbook["Overall"]
        detail = workbook["美学明细"]

        self.assertEqual(overall["B12"].value, 1)
        self.assertEqual(detail.max_row, 2)
        headers = [cell.value for cell in detail[1]]
        self.assertEqual(detail.cell(2, headers.index("图片名") + 1).value, "image-1.png")
        self.assertEqual(detail.cell(2, headers.index("美学判定") + 1).value, "A 胜")

    @patch("app_core.export_service.get_prompt_text", return_value="a red car")
    def test_dimension_detail_contains_required_fields_and_unexported_image_values(self, _prompt):
        sheet = build_workbook(self.t2i_request, self.t2i_rows)["美学明细"]
        headers = [cell.value for cell in sheet[1]]

        for header in ("任务类型", "模型 A", "模型 B", "场景", "图片名", "Prompt", "评测人", "评测模式", "评测时间（北京时间）"):
            self.assertIn(header, headers)
        self.assertIn("美学判定", headers)
        self.assertIn("评测耗时（秒）", headers)
        self.assertIn("A 坏例标签", headers)
        self.assertEqual(sheet.cell(2, headers.index("Prompt") + 1).value, "a red car")
        self.assertEqual(sheet.cell(2, headers.index("A 图片路径") + 1).value, "")
        self.assertEqual(sheet.cell(2, headers.index("A 图片状态") + 1).value, "未导出")
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet.auto_filter.ref, sheet.dimensions)
        self.assertTrue(sheet.cell(2, headers.index("Prompt") + 1).alignment.wrap_text)

    @patch("app_core.export_service.get_prompt_text", return_value="portrait prompt")
    def test_ti2i_workbook_has_fidelity_reference_columns_and_round_trips(self, _prompt):
        workbook = build_workbook(self.ti2i_request, self.ti2i_rows)
        sheet = workbook["保真度明细"]
        headers = [cell.value for cell in sheet[1]]

        self.assertIn("参考图路径", headers)
        self.assertIn("参考图状态", headers)
        self.assertNotIn("评测耗时（秒）", headers)
        self.assertNotIn("D 坏例标签", headers)
        self.assertEqual(sheet.cell(2, headers.index("参考图路径") + 1).value, "")
        self.assertEqual(sheet.cell(2, headers.index("参考图状态") + 1).value, "未导出")
        loaded = load_workbook(BytesIO(workbook_bytes(workbook)))
        self.assertEqual(loaded.sheetnames, ["Overall", "保真度明细"])

    @patch("app_core.export_service.get_prompt_text", return_value="=SUM(1, 1)")
    def test_external_text_is_not_written_as_excel_formula(self, _prompt):
        request = ExportRequest(
            task_type="T2I",
            v1="=model-b",
            v2="+model-a",
            scenes=["-scene"],
            workers=["@worker"],
            dimensions=["aesthetic"],
        )
        rows = [
            make_row(
                1,
                v_a="+model-a",
                v_b="=model-b",
                overall="+model-a",
                aesthetic="=model-b",
                scene="-scene",
                filename="@image.png",
                worker="@worker",
            )
        ]

        loaded = load_workbook(BytesIO(workbook_bytes(build_workbook(request, rows))), data_only=False)

        for sheet in loaded.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    self.assertNotEqual(cell.data_type, "f", f"{sheet.title}!{cell.coordinate}")
        self.assertEqual(loaded["Overall"]["B4"].value, "'+model-a vs =model-b")
        self.assertEqual(loaded["Overall"]["B5"].value, "'-scene")
        detail = loaded["美学明细"]
        headers = [cell.value for cell in detail[1]]
        self.assertEqual(detail.cell(2, headers.index("模型 A") + 1).value, "'+model-a")
        self.assertEqual(detail.cell(2, headers.index("模型 B") + 1).value, "'=model-b")
        self.assertEqual(detail.cell(2, headers.index("场景") + 1).value, "'-scene")
        self.assertEqual(detail.cell(2, headers.index("图片名") + 1).value, "'@image.png")
        self.assertEqual(detail.cell(2, headers.index("评测人") + 1).value, "'@worker")
        self.assertEqual(detail.cell(2, headers.index("Prompt") + 1).value, "'=SUM(1, 1)")

    @patch("app_core.export_service.get_prompt_text", return_value="cached prompt")
    def test_build_workbook_caches_prompt_by_task_scene_and_filename(self, prompt_lookup):
        request = ExportRequest(task_type="T2I", v1="A", v2="B", dimensions=["aesthetic", "logic"])
        rows = [
            make_row(1, filename="shared.png", aesthetic="A"),
            make_row(2, filename="shared.png", aesthetic="B", worker="bob"),
        ]

        build_workbook(request, rows)

        prompt_lookup.assert_called_once_with("T2I", "city", "shared.png")

    def test_overall_statistics_cover_empty_winners_ties_and_single_side_bad_cases(self):
        request = ExportRequest(task_type="T2I", v1="A", v2="B")
        cases = [
            ("empty", [], [0, 0, 0, 0, 0, 0, 0, "-", "-", 0, 0, 0, 0]),
            ("a_wins", [make_row(1, overall="A")], [1, 1, 1, 0, 0, 0, 0, "∞", 0, 0, 0, 0, 0]),
            ("b_wins", [make_row(1, overall="B")], [1, 0, 0, 0, 0, 1, 1, 0, "∞", 0, 0, 0, 0]),
            (
                "ties",
                [make_row(1, overall="tie"), make_row(2, overall="tie")],
                [2, 0, 0, 2, 1, 0, 0, 1, 1, 0, 0, 0, 0],
            ),
            (
                "a_bad_only",
                [make_row(1, overall="tie", bad_case_tags_a='["模糊失焦"]')],
                [1, 0, 0, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0],
            ),
        ]

        for name, rows, expected in cases:
            with self.subTest(name=name):
                workbook = build_workbook(request, rows)
                overall = workbook["Overall"]
                values = [overall.cell(12, column).value for column in range(2, 15)]
                self.assertEqual(values, expected)
                for column in (4, 6, 8, 12, 14):
                    self.assertEqual(overall.cell(12, column).number_format, "0.0%")

                loaded = load_workbook(BytesIO(workbook_bytes(workbook)), data_only=False)["Overall"]
                for column in (2, 3, 4, 5, 6, 7, 8, 11, 12, 13, 14):
                    self.assertEqual(loaded.cell(12, column).data_type, "n")
                for column in (9, 10):
                    expected_type = "s" if isinstance(overall.cell(12, column).value, str) else "n"
                    self.assertEqual(loaded.cell(12, column).data_type, expected_type)


if __name__ == "__main__":
    unittest.main()
