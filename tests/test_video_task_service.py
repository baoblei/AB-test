import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app_core.database import connect, init_db
from app_core.errors import AppError, ConflictError
from app_core.task_service import skip_task, start_eval_session, submit_vote


class VideoTaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "video-task.db")
        self.db_patch = patch("app_core.database.DB_PATH", self.db_path)
        self.db_patch.start()
        init_db()
        self.filenames = ["clip_01.mp4", "clip_02.mp4", "clip_03.mp4"]

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @contextmanager
    def available_videos(self):
        with patch(
            "app_core.task_service.list_scene_files", return_value=self.filenames
        ), patch("app_core.task_service.os.path.exists", return_value=True):
            yield

    def start(self, dimensions, overwrite=False):
        with self.available_videos():
            return start_eval_session(
                "T2V",
                "admin",
                "test_A_default",
                "test_B_default",
                "motion",
                "selected",
                1,
                selected_dimensions=dimensions,
                overwrite_dimensions=overwrite,
            )

    def scalar(self, query, params=()):
        conn = connect()
        value = conn.execute(query, params).fetchone()[0]
        conn.close()
        return value

    def task_id(self, filename="clip_01.mp4", status="working"):
        conn = connect()
        conn.execute(
            "UPDATE pair_tasks SET status=? WHERE filename=?",
            (status, filename),
        )
        task_id = conn.execute(
            "SELECT id FROM pair_tasks WHERE filename=?", (filename,)
        ).fetchone()[0]
        conn.commit()
        conn.close()
        return task_id

    def vote(self, task_id, dimensions, **overrides):
        values = {
            "task_type": "T2V",
            "eval_mode": "selected",
            "task_id": task_id,
            "v_left": "test_A_default",
            "v_right": "test_B_default",
            "scene": "motion",
            "filename": "clip_01.mp4",
            "worker": "ignored",
            "overall": "left",
            "text_consistency": "right",
            "structure_reasonableness": "right",
            "motion_reasonableness": "tie_good",
            "dynamism": "left",
            "physical_plausibility": "right",
            "visual_quality": "tie_bad",
            "image_consistency": "left",
            "selected_dimensions": dimensions,
            "bad_case_left": [],
            "bad_case_right": [],
            "duration_seconds": 4,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_new_scope_is_created_and_equal_set_resumes(self):
        first = self.start(["dynamism", "overall"])
        same = self.start(["overall", "dynamism"])

        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["selected_dimensions"], ["overall", "dynamism"])
        self.assertEqual(same["dimension_transition"], "equal")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM evaluation_scopes"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM pair_tasks"), 3)

    def test_strict_superset_confirms_then_restarts_all_tasks(self):
        self.start(["overall"])
        task_id = self.task_id()
        submit_vote(self.vote(task_id, ["overall"]), 1, "admin")

        confirmation = self.start(["overall", "dynamism"])
        self.assertEqual(confirmation["status"], "requires_confirmation")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM results_log"), 1)

        restarted = self.start(["dynamism", "overall"], overwrite=True)
        self.assertEqual(restarted["dimension_transition"], "superset")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM results_log"), 0)
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM pair_tasks WHERE status='pending'"), 3
        )
        stored = self.scalar("SELECT selected_dimensions FROM evaluation_scopes")
        self.assertEqual(json.loads(stored), ["overall", "dynamism"])

    def test_subset_and_incomparable_sets_are_rejected_without_mutation(self):
        self.start(["overall", "dynamism"])
        task_id = self.task_id()
        submit_vote(self.vote(task_id, ["overall", "dynamism"]), 1, "admin")

        for dimensions in (["overall"], ["overall", "visual_quality"]):
            with self.subTest(dimensions=dimensions), self.assertRaises(AppError):
                self.start(dimensions)
            self.assertEqual(self.scalar("SELECT COUNT(*) FROM results_log"), 1)
            stored = self.scalar("SELECT selected_dimensions FROM evaluation_scopes")
            self.assertEqual(json.loads(stored), ["overall", "dynamism"])

    def test_selected_vote_stores_only_selected_scores(self):
        self.start(["dynamism"])
        task_id = self.task_id()

        submit_vote(self.vote(task_id, ["dynamism"]), 1, "admin")

        conn = connect()
        row = conn.execute(
            """
            SELECT overall, text_consistency, motion_reasonableness, dynamism,
                   physical_plausibility, visual_quality, image_consistency,
                   selected_dimensions, worker
            FROM results_log WHERE task_id=?
            """,
            (task_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row[:3], (None, None, None))
        self.assertEqual(row[3], "test_A_default")
        self.assertEqual(row[4:7], (None, None, None))
        self.assertEqual(json.loads(row[7]), ["dynamism"])
        self.assertEqual(row[8], "admin")

    def test_structure_reasonableness_is_persisted_when_selected(self):
        self.start(["structure_reasonableness"])
        task_id = self.task_id()

        submit_vote(
            self.vote(
                task_id,
                ["structure_reasonableness"],
                structure_reasonableness="right",
            ),
            1,
            "admin",
        )

        conn = connect()
        row = conn.execute(
            "SELECT structure_reasonableness, selected_dimensions "
            "FROM results_log WHERE task_id=?",
            (task_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "test_B_default")
        self.assertEqual(json.loads(row[1]), ["structure_reasonableness"])

    def test_vote_rejects_missing_selected_score_and_stale_scope(self):
        self.start(["overall"])
        task_id = self.task_id()
        with self.assertRaisesRegex(AppError, "已选"):
            submit_vote(
                self.vote(task_id, ["overall"], overall=None), 1, "admin"
            )

        self.start(["overall", "dynamism"], overwrite=True)
        with self.assertRaises(ConflictError):
            submit_vote(self.vote(task_id, ["overall"]), 1, "admin")

    def test_selected_skip_records_the_active_dimension_scope(self):
        self.start(["overall", "dynamism"])
        task_id = self.task_id()

        skip_task(task_id, "T2V", 1, "selected", "admin")

        conn = connect()
        row = conn.execute(
            """
            SELECT skipped, selected_dimensions, overall, dynamism
            FROM results_log WHERE task_id=?
            """,
            (task_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 1)
        self.assertEqual(json.loads(row[1]), ["overall", "dynamism"])
        self.assertEqual(row[2:], (None, None))


if __name__ == "__main__":
    unittest.main()
