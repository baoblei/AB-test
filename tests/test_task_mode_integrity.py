import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app_core.database import connect, init_db
from app_core.errors import AppError, ConflictError
from app_core.task_service import (
    ensure_pair_tasks,
    get_eval_mode_status,
    get_progress,
    start_eval_session,
    submit_vote,
)


class TaskModeIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "mode-integrity.db")
        self.db_patch = patch("app_core.database.DB_PATH", self.db_path)
        self.db_patch.start()
        init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def add_task(self, status="working", mode="full", worker="worker", user_id=1):
        conn = connect()
        cursor = conn.execute(
            """
            INSERT INTO pair_tasks
            (task_type, v_a, v_b, scene, filename, status, worker, assigned_user_id, eval_mode)
            VALUES ('T2I', 'model-a', 'model-b', 'scene', 'sample.png', ?, ?, ?, ?)
            """,
            (status, worker, user_id, mode),
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id

    def add_result(self, task_id, mode, skipped=0, worker="worker", user_id=1):
        conn = connect()
        conn.execute(
            """
            INSERT INTO results_log
            (task_id, eval_mode, task_type, v_a, v_b, scene, filename, overall, worker, skipped, user_id)
            VALUES (?, ?, 'T2I', 'model-a', 'model-b', 'scene', 'sample.png', ?, ?, ?, ?)
            """,
            (task_id, mode, "skipped" if skipped else "model-a", worker, skipped, user_id),
        )
        conn.commit()
        conn.close()

    def vote(self, task_id, mode="full", worker="untrusted-payload"):
        return SimpleNamespace(
            task_type="T2I",
            eval_mode=mode,
            task_id=task_id,
            v_left="model-a",
            v_right="model-b",
            scene="scene",
            filename="sample.png",
            worker=worker,
            overall="left",
            aesthetic="left",
            logic="tie",
            consistency="right",
            fidelity=None,
            bad_case_left=[],
            bad_case_right=[],
            duration_seconds=3,
        )

    def test_database_binds_task_mode_and_uniquely_links_result_to_task(self):
        task_id = self.add_task()
        self.add_result(task_id, "full")

        conn = connect()
        task_columns = {row[1] for row in conn.execute("PRAGMA table_info(pair_tasks)")}
        result_columns = {row[1] for row in conn.execute("PRAGMA table_info(results_log)")}
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO results_log
                (task_id, eval_mode, task_type, v_a, v_b, scene, filename, user_id)
                VALUES (?, 'overall', 'T2I', 'model-a', 'model-b', 'scene', 'sample.png', 1)
                """,
                (task_id,),
            )
        conn.close()

        self.assertIn("eval_mode", task_columns)
        self.assertIn("task_id", result_columns)

    def test_init_db_backfills_legacy_worker_ownership(self):
        conn = connect()
        user_id = conn.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES ('legacy-user', 'hash', 'evaluator')
            """
        ).lastrowid
        valid_owner_id = conn.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES ('valid-owner', 'hash', 'evaluator')
            """
        ).lastrowid
        conn.execute(
            """
            INSERT INTO pair_tasks
            (task_type, v_a, v_b, scene, filename, status, eval_mode, worker, assigned_user_id)
            VALUES ('T2I', 'legacy-a', 'legacy-b', 'legacy-scene', 'legacy.png',
                    'completed', 'full', 'legacy-user', 999)
            """
        )
        conn.execute(
            """
            INSERT INTO pair_tasks
            (task_type, v_a, v_b, scene, filename, status, eval_mode, worker, assigned_user_id)
            VALUES ('T2I', 'legacy-a', 'legacy-b', 'legacy-scene', 'valid-owner.png',
                    'pending', 'full', 'legacy-user', ?)
            """,
            (valid_owner_id,),
        )
        conn.execute(
            """
            INSERT INTO results_log
            (eval_mode, task_type, v_a, v_b, scene, filename, worker, user_id)
            VALUES ('full', 'T2I', 'legacy-a', 'legacy-b', 'legacy-scene',
                    'legacy.png', 'legacy-user', NULL)
            """
        )
        conn.commit()
        conn.close()

        init_db()

        conn = connect()
        task_owner = conn.execute(
            "SELECT assigned_user_id FROM pair_tasks WHERE filename='legacy.png'"
        ).fetchone()[0]
        result_owner = conn.execute(
            "SELECT user_id FROM results_log WHERE filename='legacy.png'"
        ).fetchone()[0]
        preserved_owner = conn.execute(
            "SELECT assigned_user_id FROM pair_tasks WHERE filename='valid-owner.png'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(task_owner, user_id)
        self.assertEqual(result_owner, user_id)
        self.assertEqual(preserved_owner, valid_owner_id)

    def test_overall_start_binds_task_and_stale_full_submission_is_rejected(self):
        task_id = self.add_task(status="pending", mode="full")

        response = start_eval_session("T2I", "worker", "model-a", "model-b", "scene", "overall", 1)

        self.assertEqual(response["status"], "ok")
        conn = connect()
        task = conn.execute(
            "SELECT status, eval_mode FROM pair_tasks WHERE id=?", (task_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(task, ("pending", "overall"))
        conn = connect()
        conn.execute("UPDATE pair_tasks SET status='working' WHERE id=?", (task_id,))
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(ConflictError, "评测模式"):
            submit_vote(self.vote(task_id, "full"), 1, "worker")
        self.assertEqual(submit_vote(self.vote(task_id, "overall"), 1, "worker"), {"status": "ok"})
        conn = connect()
        stored_worker = conn.execute("SELECT worker FROM results_log WHERE task_id=?", (task_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(stored_worker, "worker")

    def test_full_start_requires_confirmation_then_atomically_replaces_overall(self):
        task_id = self.add_task(status="completed", mode="overall")
        self.add_result(task_id, "overall")

        response = start_eval_session("T2I", "worker", "model-a", "model-b", "scene", "full", 1)
        self.assertEqual(response["status"], "requires_confirmation")

        conn = connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM results_log").fetchone()[0], 1)
        self.assertEqual(
            conn.execute("SELECT status, eval_mode FROM pair_tasks WHERE id=?", (task_id,)).fetchone(),
            ("completed", "overall"),
        )
        conn.close()

        response = start_eval_session(
            "T2I", "worker", "model-a", "model-b", "scene", "full", 1, overwrite_overall=True
        )
        self.assertEqual(response["status"], "ok")
        conn = connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM results_log").fetchone()[0], 0)
        self.assertEqual(
            conn.execute("SELECT status, eval_mode FROM pair_tasks WHERE id=?", (task_id,)).fetchone(),
            ("pending", "full"),
        )
        conn.close()

    def test_reentering_same_mode_preserves_working_claim(self):
        task_id = self.add_task(status="working", mode="full")

        response = start_eval_session("T2I", "worker", "model-a", "model-b", "scene", "full", 1)

        self.assertEqual(response["status"], "ok")
        conn = connect()
        task = conn.execute(
            "SELECT status, eval_mode FROM pair_tasks WHERE id=?", (task_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(task, ("working", "full"))

    def test_mode_switch_racing_submit_never_creates_mixed_state(self):
        task_id = self.add_task(status="working", mode="full")
        barrier = threading.Barrier(3)
        outcomes = []
        lock = threading.Lock()

        def run_submit():
            barrier.wait()
            try:
                submit_vote(self.vote(task_id, "full"), 1, "worker")
                outcome = "submitted"
            except ConflictError:
                outcome = "submit-conflict"
            with lock:
                outcomes.append(outcome)

        def run_switch():
            barrier.wait()
            try:
                start_eval_session("T2I", "worker", "model-a", "model-b", "scene", "overall", 1)
                outcome = "switched"
            except AppError:
                outcome = "switch-rejected"
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=run_submit), threading.Thread(target=run_switch)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)

        self.assertCountEqual(
            outcomes,
            ["submitted", "switch-rejected"] if "submitted" in outcomes else ["submit-conflict", "switched"],
        )
        conn = connect()
        result_modes = {row[0] for row in conn.execute("SELECT eval_mode FROM results_log")}
        task_mode = conn.execute("SELECT eval_mode FROM pair_tasks WHERE id=?", (task_id,)).fetchone()[0]
        conn.close()
        self.assertFalse(result_modes and task_mode not in result_modes)

    def test_user_id_reclaims_legacy_alias_without_creating_duplicate_task(self):
        task_id = self.add_task(status="pending", worker="old-alias", user_id=1)
        with patch("app_core.task_service.list_scene_files", return_value=["sample.png"]):
            with patch("app_core.task_service.os.path.exists", return_value=True):
                ensure_pair_tasks("T2I", "current-name", "model-a", "model-b", "scene", 1, "full")

        conn = connect()
        rows = conn.execute(
            "SELECT id, worker, assigned_user_id FROM pair_tasks WHERE task_type='T2I'"
        ).fetchall()
        conn.close()
        self.assertEqual(rows, [(task_id, "current-name", 1)])

    def test_username_reclaims_row_with_wrong_legacy_owner(self):
        task_id = self.add_task(status="pending", worker="current-name", user_id=999)
        with patch("app_core.task_service.list_scene_files", return_value=["sample.png"]):
            with patch("app_core.task_service.os.path.exists", return_value=True):
                ensure_pair_tasks("T2I", "current-name", "model-a", "model-b", "scene", 1, "full")

        conn = connect()
        row = conn.execute(
            "SELECT id, worker, assigned_user_id FROM pair_tasks WHERE id=?", (task_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(row, (task_id, "current-name", 1))

    def test_valid_other_owner_is_not_reassigned_from_legacy_worker_name(self):
        conn = connect()
        other_user_id = conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES ('other-user', 'hash', 'evaluator')"
        ).lastrowid
        conn.commit()
        conn.close()
        original_task_id = self.add_task(
            status="pending", worker="current-name", user_id=other_user_id
        )

        with patch("app_core.task_service.list_scene_files", return_value=["sample.png"]):
            with patch("app_core.task_service.os.path.exists", return_value=True):
                ensure_pair_tasks("T2I", "current-name", "model-a", "model-b", "scene", 1, "full")

        conn = connect()
        rows = conn.execute(
            """
            SELECT id, assigned_user_id FROM pair_tasks
            WHERE task_type='T2I' AND filename='sample.png'
            ORDER BY id
            """
        ).fetchall()
        conn.close()
        self.assertIn((original_task_id, other_user_id), rows)
        self.assertIn(1, {owner_id for _task_id, owner_id in rows})

    def test_status_and_progress_use_user_id_and_do_not_double_count_skips(self):
        task_id = self.add_task(status="completed", mode="full", worker="old-alias", user_id=1)
        self.add_result(task_id, "full", skipped=1, worker="old-alias", user_id=1)

        status = get_eval_mode_status(
            "T2I", "current-name", "model-a", "model-b", "scene", user_id=1
        )
        progress = get_progress(
            "T2I", "current-name", "model-a", "model-b", "scene", "full", user_id=1
        )

        self.assertEqual(status["full_total"], 1)
        self.assertEqual(
            progress,
            {"total": 1, "completed": 0, "skipped": 1, "remaining": 0, "percent": 100.0},
        )

    def test_progress_ignores_orphaned_legacy_skip_rows(self):
        task_id = self.add_task(status="completed", mode="full")
        self.add_result(task_id, "full", skipped=0)
        conn = connect()
        conn.execute(
            """
            INSERT INTO results_log
            (task_id, eval_mode, task_type, v_a, v_b, scene, filename, overall,
             worker, skipped, user_id)
            VALUES (NULL, 'full', 'T2I', 'model-a', 'model-b', 'scene',
                    'removed.png', 'skipped', 'worker', 1, 1)
            """
        )
        conn.commit()
        conn.close()

        progress = get_progress(
            "T2I", "worker", "model-a", "model-b", "scene", "full", user_id=1
        )

        self.assertEqual(
            progress,
            {"total": 1, "completed": 1, "skipped": 0, "remaining": 0, "percent": 100.0},
        )

    def test_submit_rolls_back_task_when_result_insert_fails(self):
        task_id = self.add_task(status="working", mode="full")
        conn = connect()
        conn.execute(
            """
            CREATE TRIGGER reject_result_insert
            BEFORE INSERT ON results_log
            BEGIN
                SELECT RAISE(ABORT, 'forced insert failure');
            END
            """
        )
        conn.commit()
        conn.close()

        with self.assertRaises(sqlite3.IntegrityError):
            submit_vote(self.vote(task_id, "full"), 1, "worker")

        conn = connect()
        status = conn.execute("SELECT status FROM pair_tasks WHERE id=?", (task_id,)).fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM results_log").fetchone()[0]
        conn.close()
        self.assertEqual(status, "working")
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
