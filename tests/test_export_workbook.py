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


if __name__ == "__main__":
    unittest.main()
