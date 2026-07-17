import unittest
from pathlib import Path


class AdminRoleUIContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (
            Path(__file__).resolve().parents[1] / "templates" / "admin.html"
        ).read_text(encoding="utf-8")

    def test_role_selector_contains_all_three_roles(self):
        for value in ('value="admin"', 'value="manager"', 'value="evaluator"'):
            self.assertIn(value, self.html)

    def test_role_selector_labels_all_three_roles(self):
        for label in ("超级管理员", "管理员", "评测员"):
            self.assertIn(label, self.html)

    def test_role_selector_updates_the_selected_users_role(self):
        self.assertIn('onchange="updateUserRole(${u.id}, this.value)"', self.html)
        self.assertIn("async function updateUserRole(userId, role)", self.html)
        self.assertIn(
            "`/api/admin/users/${userId}/role?role=${encodeURIComponent(role)}`",
            self.html,
        )
        self.assertIn("method: 'PUT'", self.html)

    def test_success_restores_the_user_list(self):
        function = self._update_role_function()
        self.assertIn("if (!res.ok)", function)
        self.assertIn("loadUsers();", function)

    def test_failure_displays_server_detail_and_restores_the_user_list(self):
        function = self._update_role_function()
        self.assertIn("await res.json()", function)
        self.assertIn("alert(error.detail)", function)
        self.assertGreaterEqual(function.count("loadUsers();"), 2)

    def _update_role_function(self):
        start = self.html.find("async function updateUserRole")
        self.assertNotEqual(start, -1, "updateUserRole function is missing")
        end = self.html.find("\n    //", start)
        return self.html[start : end if end != -1 else None]


if __name__ == "__main__":
    unittest.main()
