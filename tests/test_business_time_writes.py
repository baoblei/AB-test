import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app_core.admin_service import admin_stats
from app_core.database import connect, init_db, log_operation
from app_core.schemas import UserLogin, UserRegister
from app_core.task_service import skip_task, submit_vote
from app_core.user_service import login_user, register_user


class BusinessTimeWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "business-time.db")
        self.db_path_patch = patch("app_core.database.DB_PATH", self.db_path)
        self.db_path_patch.start()
        init_db()

        conn = connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO pair_tasks (task_type, v_a, v_b, scene, filename, status, worker, assigned_user_id)
            VALUES ('T2I', 'model-a', 'model-b', 'scene', 'vote.png', 'working', 'worker', 1)
            """
        )
        full_task_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO pair_tasks (task_type, v_a, v_b, scene, filename, status, worker, assigned_user_id)
            VALUES ('T2I', 'model-a', 'model-b', 'scene', 'skip.png', 'working', 'worker', 1)
            """
        )
        self.skip_task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        self.full_vote = SimpleNamespace(
            task_type="T2I",
            eval_mode="full",
            task_id=full_task_id,
            v_left="model-a",
            v_right="model-b",
            scene="scene",
            filename="vote.png",
            worker="worker",
            overall="tie",
            aesthetic="tie",
            logic="tie",
            consistency="tie",
            fidelity=None,
            bad_case_left=[],
            bad_case_right=[],
            duration_seconds=3,
        )

    def tearDown(self):
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_new_database_defaults_use_beijing_iso(self):
        definitions = {
            row[0]: row[1]
            for row in connect().execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND name IN ('users', 'operation_logs', 'results_log')"
            )
        }
        expected_default = "DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', '+8 hours') || '+08:00')"

        self.assertIn(expected_default, definitions["users"])
        self.assertIn(expected_default, definitions["operation_logs"])
        self.assertIn(expected_default, definitions["results_log"])

    def test_default_admin_writes_beijing_iso(self):
        Path(self.db_path).unlink()
        expected_timestamp = "2026-07-15T09:02:03+08:00"
        with patch("app_core.database.now_beijing_iso", return_value=expected_timestamp):
            init_db()
        value = connect().execute("SELECT created_at FROM users WHERE username='admin'").fetchone()[0]

        self.assertEqual(value, expected_timestamp)

    def test_log_operation_writes_beijing_iso(self):
        log_operation(1, "test", "details")
        value = connect().execute(
            "SELECT timestamp FROM operation_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$")

    def test_registration_and_last_login_write_beijing_iso(self):
        register_user(UserRegister(username="evaluator", password="password", email="evaluator@example.com"))
        user_id, created_at = connect().execute(
            "SELECT id, created_at FROM users WHERE username='evaluator'"
        ).fetchone()
        login_user(UserLogin(username="evaluator", password="password"))
        last_login = connect().execute("SELECT last_login FROM users WHERE id=?", (user_id,)).fetchone()[0]

        self.assertRegex(created_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$")
        self.assertRegex(last_login, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$")

    def test_submit_and_skip_write_beijing_iso(self):
        submit_vote(self.full_vote, 1)
        skip_task(self.skip_task_id, "T2I", 1, "full")
        values = [row[0] for row in connect().execute("SELECT timestamp FROM results_log ORDER BY id")]

        self.assertTrue(all(value.endswith("+08:00") for value in values))

    def test_admin_today_uses_beijing_date(self):
        beijing_date = connect().execute("SELECT DATE('now', '+2 days')").fetchone()[0]
        with patch("app_core.admin_service.beijing_today", return_value=beijing_date, create=True):
            conn = connect()
            conn.execute(
                "INSERT INTO results_log (timestamp, skipped) VALUES (? || 'T00:01:00+08:00', 0)",
                (beijing_date,),
            )
            conn.commit()
            conn.close()

            self.assertEqual(admin_stats()["today_eval"], 1)
