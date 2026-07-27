import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app_core.database import connect, init_db
from app_core.errors import AppError
from app_core.task_service import skip_task, submit_vote


class FourWayTaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch(
            "app_core.database.DB_PATH",
            str(Path(self.temp_dir.name) / "four-way.db"),
        )
        self.db_patch.start()
        init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def add_task(self, filename="sample.png"):
        conn = connect()
        task_id = conn.execute(
            """
            INSERT INTO pair_tasks
            (task_type, v_a, v_b, scene, filename, status, eval_mode, worker, assigned_user_id)
            VALUES ('T2I', 'model-a', 'model-b', 'scene', ?, 'working', 'full', 'worker', 1)
            """,
            (filename,),
        ).lastrowid
        conn.commit()
        conn.close()
        return task_id

    def vote(self, task_id, **overrides):
        payload = dict(
            task_type="T2I", eval_mode="full", task_id=task_id,
            v_left="model-b", v_right="model-a", scene="scene",
            filename="sample.png", worker="ignored", overall="tie_good",
            aesthetic="left", logic="tie_bad", consistency="right",
            fidelity=None, bad_case_left=[], bad_case_right=[], duration_seconds=3,
        )
        payload.update(overrides)
        return SimpleNamespace(**payload)

    def task_status(self, task_id):
        conn = connect()
        value = conn.execute("SELECT status FROM pair_tasks WHERE id=?", (task_id,)).fetchone()[0]
        conn.close()
        return value

    def test_submit_maps_sides_and_preserves_both_tie_subtypes(self):
        task_id = self.add_task()
        self.assertEqual(submit_vote(self.vote(task_id), 1, "worker"), {"status": "ok"})
        conn = connect()
        row = conn.execute(
            "SELECT overall, aesthetic, logic, consistency, fidelity FROM results_log WHERE task_id=?",
            (task_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row, ("tie_good", "model-b", "tie_bad", "model-a", None))

    def test_full_vote_requires_explicit_overall(self):
        task_id = self.add_task()
        with self.assertRaisesRegex(AppError, "请完成所有评分维度"):
            submit_vote(self.vote(task_id, overall=None), 1, "worker")
        self.assertEqual(self.task_status(task_id), "working")

    def test_unknown_choice_is_rejected_instead_of_becoming_tie(self):
        task_id = self.add_task()
        with self.assertRaisesRegex(AppError, "无效评测选项"):
            submit_vote(self.vote(task_id, logic="tie"), 1, "worker")
        self.assertEqual(self.task_status(task_id), "working")

    def test_skip_stores_no_result_placeholders(self):
        task_id = self.add_task()
        self.assertEqual(skip_task(task_id, "T2I", 1), {"status": "ok"})
        conn = connect()
        row = conn.execute(
            "SELECT overall, aesthetic, logic, consistency, fidelity, skipped FROM results_log WHERE task_id=?",
            (task_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row, (None, None, None, None, None, 1))
