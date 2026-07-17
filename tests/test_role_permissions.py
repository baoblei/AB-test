import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import main
from app_core import admin_service, auth, database, user_service
from app_core.errors import AppError
from app_core.schemas import UserRegister


class RoleAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "roles.db")
        self.db_path_patch = patch("app_core.database.DB_PATH", self.db_path)
        self.db_path_patch.start()
        database.init_db()
        self.connect_patches = [
            patch("app_core.auth.connect", side_effect=database.connect),
            patch("app_core.user_service.connect", side_effect=database.connect),
            patch("app_core.admin_service.connect", side_effect=database.connect),
        ]
        for connect_patch in self.connect_patches:
            connect_patch.start()

    def tearDown(self):
        for connect_patch in reversed(self.connect_patches):
            connect_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_registration_explicitly_writes_evaluator_role(self):
        user_service.register_user(
            UserRegister(username="new-user", password="password", email="new@example.com")
        )

        role = database.connect().execute(
            "SELECT role FROM users WHERE username=?", ("new-user",)
        ).fetchone()[0]
        self.assertEqual(role, "evaluator")

    def test_data_manager_accepts_admin_and_manager_and_rejects_evaluator(self):
        self.assertEqual(asyncio.run(auth.require_data_manager({"role": "admin"}))["role"], "admin")
        self.assertEqual(asyncio.run(auth.require_data_manager({"role": "manager"}))["role"], "manager")
        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.require_data_manager({"role": "evaluator"}))
        self.assertEqual(context.exception.status_code, 403)
        self.assertEqual(context.exception.detail, "当前用户没有权限，请联系管理员")

    def test_data_manager_requires_login(self):
        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.require_data_manager(None))
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail, "请先登录")

    def test_upload_and_export_routes_require_data_manager(self):
        expected = {
            ("/api/upload_dataset", "POST"),
            ("/api/upload", "POST"),
            ("/api/upload_ref", "POST"),
            ("/api/export", "GET"),
            ("/api/export_options", "GET"),
            ("/api/export/preview", "POST"),
            ("/api/export", "POST"),
        }
        actual = set()
        for route in main.app.routes:
            methods = getattr(route, "methods", None) or set()
            matching = {(route.path, method) for method in methods if (route.path, method) in expected}
            if matching:
                self.assertIn(auth.require_data_manager, [item.call for item in route.dependant.dependencies])
                actual.update(matching)
        self.assertEqual(actual, expected)

    def test_admin_routes_still_require_admin(self):
        admin_routes = [route for route in main.app.routes if route.path.startswith("/api/admin/")]
        self.assertTrue(admin_routes)
        for route in admin_routes:
            self.assertIn(auth.require_admin, [item.call for item in route.dependant.dependencies])


class RoleMutationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "role-mutations.db")
        self.db_path_patch = patch("app_core.database.DB_PATH", self.db_path)
        self.db_path_patch.start()
        database.init_db()
        self.connect_patches = [
            patch("app_core.auth.connect", side_effect=database.connect),
            patch("app_core.user_service.connect", side_effect=database.connect),
            patch("app_core.admin_service.connect", side_effect=database.connect),
        ]
        for connect_patch in self.connect_patches:
            connect_patch.start()

        conn = database.connect()
        self.admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        conn.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
            ("other-admin", "hash", "admin"),
        )
        self.other_admin_id = conn.execute(
            "SELECT id FROM users WHERE username='other-admin'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
            ("target", "hash", "evaluator"),
        )
        self.target_id = conn.execute("SELECT id FROM users WHERE username='target'").fetchone()[0]
        conn.commit()
        conn.close()

    def tearDown(self):
        for connect_patch in reversed(self.connect_patches):
            connect_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def role_of(self, user_id):
        conn = database.connect()
        role = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()[0]
        conn.close()
        return role

    def active_of(self, user_id):
        conn = database.connect()
        active = conn.execute("SELECT is_active FROM users WHERE id=?", (user_id,)).fetchone()[0]
        conn.close()
        return active

    def test_valid_role_changes_are_persisted_and_logged(self):
        for role in ("admin", "manager", "evaluator"):
            with self.subTest(role=role):
                self.assertEqual(
                    admin_service.update_user_role(self.target_id, role, self.admin_id),
                    {"status": "ok"},
                )
                self.assertEqual(self.role_of(self.target_id), role)

        conn = database.connect()
        logs = conn.execute(
            "SELECT action, details FROM operation_logs WHERE user_id=? ORDER BY id",
            (self.admin_id,),
        ).fetchall()
        conn.close()
        self.assertEqual(len(logs), 3)
        self.assertTrue(all(action == "admin_action" for action, _ in logs))
        self.assertIn(f"更新用户 {self.target_id} 角色为 evaluator", logs[-1][1])

    def test_invalid_role_is_rejected_without_database_change(self):
        with self.assertRaises(AppError):
            admin_service.update_user_role(self.target_id, "owner", self.admin_id)
        self.assertEqual(self.role_of(self.target_id), "evaluator")

    def test_admin_cannot_change_own_role(self):
        with self.assertRaises(AppError):
            admin_service.update_user_role(self.admin_id, "manager", self.admin_id)
        self.assertEqual(self.role_of(self.admin_id), "admin")

    def test_last_active_admin_cannot_be_demoted(self):
        conn = database.connect()
        conn.execute("UPDATE users SET is_active=0 WHERE id=?", (self.other_admin_id,))
        conn.commit()
        conn.close()

        with self.assertRaises(AppError):
            admin_service.update_user_role(self.admin_id, "manager", self.other_admin_id)
        self.assertEqual(self.role_of(self.admin_id), "admin")

    def test_last_active_admin_cannot_be_disabled(self):
        conn = database.connect()
        conn.execute("UPDATE users SET is_active=0 WHERE id=?", (self.other_admin_id,))
        conn.commit()
        conn.close()

        with self.assertRaises(AppError):
            admin_service.update_user_status(self.admin_id, 0, self.other_admin_id)
        self.assertEqual(self.active_of(self.admin_id), 1)

    def test_nonbinary_status_is_rejected_without_database_change(self):
        with self.assertRaises(AppError):
            admin_service.update_user_status(self.target_id, 2, self.admin_id)
        self.assertEqual(self.active_of(self.target_id), 1)

    def test_status_update_is_persisted_and_logged(self):
        self.assertEqual(
            admin_service.update_user_status(self.target_id, 0, self.admin_id),
            {"status": "ok"},
        )
        self.assertEqual(self.active_of(self.target_id), 0)
        conn = database.connect()
        log = conn.execute(
            "SELECT action, details FROM operation_logs WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (self.admin_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(log, ("admin_action", f"更新用户 {self.target_id} 状态为 0"))


if __name__ == "__main__":
    unittest.main()
