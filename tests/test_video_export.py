import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app_core.database import connect, init_db
from app_core.export_service import (
    build_archive,
    build_image_manifest,
    build_workbook,
    filter_rows,
    get_export_options,
)
from app_core.schemas import ExportRequest
from app_core.storage import get_ref_image_path
from app_core.user_service import get_my_history


def make_video_row(row_id, **overrides):
    row = {
        "id": row_id,
        "eval_mode": "selected",
        "task_type": "T2V",
        "v_a": "A",
        "v_b": "B",
        "scene": "motion",
        "filename": f"clip-{row_id}.mp4",
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
        "selected_dimensions": '["overall", "dynamism"]',
        "worker": "alice",
        "timestamp": "2026-07-28T12:00:00+08:00",
        "duration_seconds": 4,
        "skipped": 0,
        "user_id": 1,
        "bad_case_tags_a": "[]",
        "bad_case_tags_b": "[]",
        "bad_case_categories_a": "[]",
        "bad_case_categories_b": "[]",
    }
    row.update(overrides)
    return row


class VideoExportTests(unittest.TestCase):
    def test_selected_mode_filters_each_dimension_by_non_null_score(self):
        rows = [
            make_video_row(1, dynamism="A"),
            make_video_row(2, overall="B", selected_dimensions='["overall"]'),
        ]
        request = ExportRequest(
            task_type="T2V",
            v1="A",
            v2="B",
            dimensions=["overall", "dynamism"],
            eval_modes=["selected"],
            include_images=True,
        )

        self.assertEqual([row["id"] for row in filter_rows(rows, request, "overall")], [2])
        self.assertEqual([row["id"] for row in filter_rows(rows, request, "dynamism")], [1])

    @patch("app_core.export_service.get_prompt_text", return_value="a moving subject")
    def test_video_workbook_uses_video_headers_and_keeps_null_scores_empty(self, _prompt):
        request = ExportRequest(
            task_type="T2V",
            v1="A",
            v2="B",
            dimensions=["overall", "structure_reasonableness", "dynamism"],
            eval_modes=["selected"],
        )
        rows = [
            make_video_row(1, structure_reasonableness="B", dynamism="A"),
            make_video_row(2, overall="B", selected_dimensions='["overall"]'),
        ]

        sheet = build_workbook(request, rows)["motion"]
        groups = [cell.value for cell in sheet[1]]
        headers = [cell.value for cell in sheet[2]]

        self.assertIn("视频信息", groups)
        self.assertIn("整体", headers)
        self.assertIn("结构合理性", headers)
        self.assertIn("动态度", headers)
        self.assertIn("A 视频路径", headers)
        self.assertIn("A 首帧路径", headers)
        values = {
            sheet.cell(row, headers.index("文件名") + 1).value: (
                sheet.cell(row, headers.index("整体") + 1).value,
                sheet.cell(row, headers.index("动态度") + 1).value,
            )
            for row in range(3, sheet.max_row + 1)
        }
        self.assertEqual(values["clip-1.mp4"], (None, "A"))
        self.assertEqual(values["clip-2.mp4"], ("B", None))
        structure_column = headers.index("结构合理性") + 1
        self.assertEqual(sheet.cell(3, structure_column).value, "B")

    def test_video_archive_keeps_original_media_posters_and_ti2v_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = {}
            posters = {}
            for model, suffix in (("A", ".mp4"), ("B", ".webm")):
                media[model] = root / f"{model}{suffix}"
                media[model].write_bytes(f"original-{model}".encode())
                posters[model] = root / f"{model}.webp"
                posters[model].write_bytes(f"poster-{model}".encode())
            reference = root / "ref.png"
            reference.write_bytes(b"reference")
            row = make_video_row(
                1,
                task_type="TI2V",
                filename="clip.mp4",
                overall="A",
                image_consistency="B",
                selected_dimensions='["overall", "image_consistency"]',
            )
            request = ExportRequest(
                task_type="TI2V",
                v1="A",
                v2="B",
                dimensions=["overall", "image_consistency"],
                eval_modes=["selected"],
                include_images=True,
            )

            manifest = build_image_manifest(
                request,
                [row],
                result_path_resolver=lambda _task, model, _scene, _filename: str(media[model]),
                ref_path_resolver=lambda *_args: str(reference),
                poster_path_resolver=lambda _task, model, _scene, _filename: str(posters[model]),
            )
            archive_path = root / "video-export.zip"
            build_archive(
                request,
                b"xlsx",
                [row],
                archive_path=str(archive_path),
                image_manifest=manifest,
            )

            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    [
                        "images/motion/ref/clip.png",
                        "posters/motion/A/clip.webp",
                        "posters/motion/B/clip.webp",
                        "videos/motion/A/clip.mp4",
                        "videos/motion/B/clip.webm",
                        "评测结果.xlsx",
                    ],
                )
                self.assertEqual(archive.read("videos/motion/A/clip.mp4"), b"original-A")
                self.assertEqual(archive.read("videos/motion/B/clip.webm"), b"original-B")
                self.assertEqual(archive.read("images/motion/ref/clip.png"), b"reference")

    def test_export_options_include_overall_for_video_tasks(self):
        with patch("app_core.export_service.fetch_base_rows", return_value=[]):
            options = get_export_options("T2V", "B", "A")

        self.assertEqual(
            [item["key"] for item in options["dimensions"]],
            [
                "overall",
                "text_consistency",
                "structure_reasonableness",
                "motion_reasonableness",
                "dynamism",
                "physical_plausibility",
                "visual_quality",
            ],
        )
        self.assertEqual(options["media_type"], "video")

    def test_ti2v_reference_image_matches_video_filename_by_stem(self):
        with tempfile.TemporaryDirectory() as temporary:
            ref_root = Path(temporary) / "refs"
            (ref_root / "motion").mkdir(parents=True)
            expected = ref_root / "motion" / "clip.png"
            expected.write_bytes(b"png")

            with patch("app_core.storage.get_ref_root", return_value=str(ref_root)):
                with patch("app_core.storage.REF_IMAGE_DIR", str(ref_root)):
                    resolved = get_ref_image_path("TI2V", "motion", "clip.mp4")

        self.assertEqual(resolved, str(expected))

    def test_personal_history_exposes_selected_dimensions_and_video_scores(self):
        with tempfile.TemporaryDirectory() as temporary:
            db_path = str(Path(temporary) / "history.db")
            with patch("app_core.database.DB_PATH", db_path):
                init_db()
                conn = connect()
                row = make_video_row(
                    1,
                    overall="A",
                    text_consistency="B",
                    structure_reasonableness="B",
                    motion_reasonableness="tie_good",
                    dynamism="A",
                    physical_plausibility="B",
                    visual_quality="tie_bad",
                    image_consistency=None,
                    selected_dimensions='["overall", "text_consistency", "dynamism"]',
                )
                columns = [column for column in row if column != "id"]
                conn.execute(
                    f"INSERT INTO results_log ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(row[column] for column in columns),
                )
                conn.commit()
                conn.close()

                history = get_my_history(1)

        self.assertEqual(history[0]["selected_dimensions"], ["overall", "text_consistency", "dynamism"])
        self.assertEqual(history[0]["structure_reasonableness"], "B")
        for key in (
            "text_consistency",
            "structure_reasonableness",
            "motion_reasonableness",
            "dynamism",
            "physical_plausibility",
            "visual_quality",
            "image_consistency",
        ):
            self.assertIn(key, history[0])

    def test_dashboard_export_copy_and_modes_are_video_aware(self):
        html = Path("templates/dashboard.html").read_text(encoding="utf-8")

        self.assertIn('id="export-media-label"', html)
        self.assertIn('id="export-eval-mode-group"', html)
        self.assertIn('state.config?.media_type === "video" ? ["selected"]', html)
        self.assertIn('mediaNoun = isVideo ? "视频" : "图片"', html)


if __name__ == "__main__":
    unittest.main()
