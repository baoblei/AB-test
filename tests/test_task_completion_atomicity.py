import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app_core.database import connect, init_db, reset_working_tasks
from app_core.errors import ConflictError
from app_core.task_service import get_next_task, skip_task, submit_vote


class TaskCompletionAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "atomic.db")
        self.db_patch = patch("app_core.database.DB_PATH", self.db_path)
        self.db_patch.start()
        init_db()
        self.task_id = self.add_task("sample.png")
        self.vote = SimpleNamespace(
            task_type="T2I",
            eval_mode="full",
            task_id=self.task_id,
            v_left="model-a",
            v_right="model-b",
            scene="scene",
            filename="sample.png",
            worker="worker",
            overall=None,
            aesthetic="left",
            logic="tie",
            consistency="right",
            fidelity=None,
            bad_case_left=[],
            bad_case_right=[],
            duration_seconds=3,
        )

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def add_task(self, filename, user_id=1, status="working"):
        conn = connect()
        cursor = conn.execute(
            """
            INSERT INTO pair_tasks
            (task_type, v_a, v_b, scene, filename, status, worker, assigned_user_id)
            VALUES ('T2I', 'model-a', 'model-b', 'scene', ?, ?, 'worker', ?)
            """,
            (filename, status, user_id),
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id

    def result_count(self):
        conn = connect()
        count = conn.execute("SELECT COUNT(*) FROM results_log").fetchone()[0]
        conn.close()
        return count

    def test_duplicate_submit_inserts_one_result_and_rejects_second_claim(self):
        self.assertEqual(submit_vote(self.vote, 1, "worker"), {"status": "ok"})

        with self.assertRaisesRegex(ConflictError, "任务已完成、已失效或不属于当前用户"):
            submit_vote(self.vote, 1, "worker")

        conn = connect()
        status = conn.execute("SELECT status FROM pair_tasks WHERE id=?", (self.task_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(status, "completed")
        self.assertEqual(self.result_count(), 1)

    def test_duplicate_submit_endpoint_returns_conflict(self):
        import main

        client = TestClient(main.app)
        main.app.dependency_overrides[main.require_login] = lambda: {"id": 1, "username": "worker"}
        try:
            first = client.post("/api/submit", json=vars(self.vote))
            second = client.post("/api/submit", json=vars(self.vote))
        finally:
            main.app.dependency_overrides.pop(main.require_login, None)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"], "任务已完成、已失效或不属于当前用户")

    def test_task_scope_endpoints_use_authenticated_username(self):
        import main

        client = TestClient(main.app)
        main.app.dependency_overrides[main.require_login] = lambda: {"id": 1, "username": "worker"}
        common_params = {
            "task_type": "T2I",
            "worker": "spoofed-worker",
            "v1": "model-a",
            "v2": "model-b",
            "scene": "scene",
        }
        try:
            with patch.object(main, "get_eval_mode_status_service", return_value={"status": "ok"}) as status:
                self.assertEqual(client.get("/api/eval_mode_status", params=common_params).status_code, 200)
            with patch.object(main, "start_eval_session_service", return_value={"status": "ok"}) as start:
                self.assertEqual(client.post("/api/start_eval_session", params=common_params).status_code, 200)
            with patch.object(main, "get_next_task", return_value={"status": "finished"}) as next_task:
                self.assertEqual(client.get("/api/get_task", params=common_params).status_code, 200)
            with patch.object(main, "get_progress_service", return_value={"total": 0}) as progress:
                self.assertEqual(client.get("/api/progress", params=common_params).status_code, 200)
        finally:
            main.app.dependency_overrides.pop(main.require_login, None)

        status.assert_called_once_with("T2I", "worker", "model-a", "model-b", "scene", 1)
        start.assert_called_once_with("T2I", "worker", "model-a", "model-b", "scene", "full", 1, False)
        next_task.assert_called_once_with("T2I", "worker", "model-a", "model-b", "scene", 1, "full")
        progress.assert_called_once_with("T2I", "worker", "model-a", "model-b", "scene", "full", 1)

    def test_duplicate_skip_inserts_one_result_and_rejects_second_claim(self):
        self.assertEqual(skip_task(self.task_id, "T2I", 1), {"status": "ok"})

        with self.assertRaisesRegex(ConflictError, "任务已完成、已失效或不属于当前用户"):
            skip_task(self.task_id, "T2I", 1)

        self.assertEqual(self.result_count(), 1)

    def test_submit_skip_race_has_exactly_one_winner_and_one_result(self):
        barrier = threading.Barrier(3)
        outcomes = []
        outcome_lock = threading.Lock()

        def run(action):
            barrier.wait()
            try:
                action()
                outcome = "ok"
            except ConflictError:
                outcome = "conflict"
            with outcome_lock:
                outcomes.append(outcome)

        submit_thread = threading.Thread(target=run, args=(lambda: submit_vote(self.vote, 1, "worker"),))
        skip_thread = threading.Thread(target=run, args=(lambda: skip_task(self.task_id, "T2I", 1),))
        submit_thread.start()
        skip_thread.start()
        barrier.wait()
        submit_thread.join(timeout=5)
        skip_thread.join(timeout=5)

        self.assertFalse(submit_thread.is_alive())
        self.assertFalse(skip_thread.is_alive())
        self.assertCountEqual(outcomes, ["ok", "conflict"])
        self.assertEqual(self.result_count(), 1)

    def test_submit_rejects_other_user_and_payload_mismatch_without_mutation(self):
        with self.assertRaises(ConflictError):
            submit_vote(self.vote, 2, "other-worker")

        tampered_vote = SimpleNamespace(**vars(self.vote))
        tampered_vote.filename = "other.png"
        with self.assertRaisesRegex(ConflictError, "提交内容与当前任务不一致"):
            submit_vote(tampered_vote, 1, "worker")

        self.assertEqual(self.result_count(), 0)
        conn = connect()
        status = conn.execute("SELECT status FROM pair_tasks WHERE id=?", (self.task_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(status, "working")

    def test_get_next_task_only_returns_work_owned_by_current_user(self):
        with patch("app_core.task_service.ensure_pair_tasks"):
            self.assertEqual(
                get_next_task("T2I", "worker", "model-a", "model-b", "scene", 2),
                {"status": "finished"},
            )
            with patch("app_core.task_service.get_prompt_text", return_value="prompt"):
                with patch("app_core.task_service.get_result_image_url", return_value="/image.png"):
                    task = get_next_task("T2I", "worker", "model-a", "model-b", "scene", 1)

        self.assertEqual(task["task_id"], self.task_id)

    def test_concurrent_get_next_task_reuses_one_working_claim(self):
        conn = connect()
        conn.execute("UPDATE pair_tasks SET status='completed' WHERE id=?", (self.task_id,))
        conn.commit()
        conn.close()
        pending_ids = {self.add_task("pending-a.png", status="pending"), self.add_task("pending-b.png", status="pending")}
        barrier = threading.Barrier(3)
        task_ids = []
        result_lock = threading.Lock()

        def load_task():
            barrier.wait()
            task = get_next_task("T2I", "worker", "model-a", "model-b", "scene", 1)
            with result_lock:
                task_ids.append(task["task_id"])

        with patch("app_core.task_service.ensure_pair_tasks"):
            with patch("app_core.task_service.get_prompt_text", return_value="prompt"):
                with patch("app_core.task_service.get_result_image_url", return_value="/image.png"):
                    threads = [threading.Thread(target=load_task) for _ in range(2)]
                    for thread in threads:
                        thread.start()
                    barrier.wait()
                    for thread in threads:
                        thread.join(timeout=5)

        self.assertEqual(len(task_ids), 2)
        self.assertEqual(len(set(task_ids)), 1)
        self.assertIn(task_ids[0], pending_ids)
        conn = connect()
        working_count = conn.execute("SELECT COUNT(*) FROM pair_tasks WHERE status='working'").fetchone()[0]
        conn.close()
        self.assertEqual(working_count, 1)

    def test_startup_reset_preserves_worker_and_owner_for_reclaim(self):
        reset_working_tasks()

        conn = connect()
        task = conn.execute(
            "SELECT status, worker, assigned_user_id FROM pair_tasks WHERE id=?", (self.task_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(task, ("pending", "worker", 1))


if __name__ == "__main__":
    unittest.main()
