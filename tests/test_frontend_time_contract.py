import re
import unittest
from pathlib import Path


TEMPLATES = Path("templates")


class FrontendTimeContractTests(unittest.TestCase):
    def read_template(self, name):
        return (TEMPLATES / name).read_text(encoding="utf-8")

    def function_source(self, html, name):
        match = re.search(
            rf"function {name}\([^)]*\) \{{([\s\S]*?)\n        \}}",
            html,
        )
        self.assertIsNotNone(match, f"missing function {name}")
        return match.group(0)

    def test_all_business_time_pages_use_stable_formatter(self):
        for template in ("dashboard.html", "profile.html", "admin.html"):
            with self.subTest(template=template):
                html = self.read_template(template)
                formatter = self.function_source(html, "formatBusinessTime")
                self.assertIn('if (!value) return "-";', formatter)
                self.assertIn('replace("T", " ")', formatter)
                self.assertIn('replace("+08:00", "")', formatter)
                self.assertNotIn("new Date", formatter)

    def test_all_stored_business_time_fields_use_formatter(self):
        expectations = {
            "dashboard.html": ("formatBusinessTime(row.time)", "formatBusinessTime(row.time)"),
            "profile.html": (
                "formatBusinessTime(data.created_at)",
                "formatBusinessTime(r.timestamp)",
            ),
            "admin.html": (
                "formatBusinessTime(u.created_at)",
                "formatBusinessTime(u.last_login)",
                "formatBusinessTime(l.timestamp)",
            ),
        }
        for template, calls in expectations.items():
            html = self.read_template(template)
            for call in set(calls):
                with self.subTest(template=template, call=call):
                    self.assertGreaterEqual(html.count(call), calls.count(call))

    def test_dashboard_last_update_is_explicitly_beijing_time(self):
        html = self.read_template("dashboard.html")
        formatter = self.function_source(html, "formatBeijingNow")
        self.assertIn('timeZone: "Asia/Shanghai"', formatter)
        self.assertIn("formatBeijingNow()", html)
        self.assertNotIn("new Date().toLocaleTimeString()", html)

    def test_evaluation_wait_helper_observes_all_compare_images(self):
        html = self.read_template("index.html")
        helper = self.function_source(html, "waitForTaskImages")
        self.assertIn('document.querySelectorAll("#compare-grid img")', helper)
        self.assertIn("img.complete", helper)
        self.assertIn('img.addEventListener("load", finish', helper)
        self.assertIn('img.addEventListener("error", finish', helper)
        self.assertIn("clearTimeout(timeout)", helper)
        self.assertIn("removeEventListener", helper)
        self.assertIn("setTimeout(finish, timeoutMs)", helper)

    def test_timer_resets_then_waits_for_images_before_starting(self):
        html = self.read_template("index.html")
        loader = self.function_source(html, "loadNextTask")
        self.assertIn("stopTimer();", loader)
        self.assertIn("startTime = null;", loader)
        self.assertIn("get_task", loader)
        self.assertLess(loader.index("stopTimer();"), loader.index("get_task"))
        self.assertLess(loader.index("startTime = null;"), loader.index("get_task"))
        self.assertIn('document.getElementById("timer").textContent = "00:00";', loader)
        self.assertLess(loader.index("await waitForTaskImages();"), loader.index("startTimer();"))
        self.assertNotIn("startTimer();\n            const params", loader)

    def test_finished_or_error_tasks_do_not_start_timer(self):
        html = self.read_template("index.html")
        loader = self.function_source(html, "loadNextTask")
        finished = loader[loader.index('if (task.status === "finished")'):loader.index("state.currentTask = task;")]
        self.assertNotIn("startTimer", finished)
        self.assertIn("try {", loader)
        self.assertIn("catch", loader)

    def test_generation_guard_blocks_stale_image_waits(self):
        html = self.read_template("index.html")
        self.assertIn("let loadGeneration = 0;", html)
        loader = self.function_source(html, "loadNextTask")
        self.assertIn("const generation = ++loadGeneration;", loader)
        self.assertIn("if (generation !== loadGeneration) return;", loader)

    def test_start_timer_writes_initial_zero_and_stop_only_clears_interval(self):
        html = self.read_template("index.html")
        start = self.function_source(html, "startTimer")
        stop = self.function_source(html, "stopTimer")
        self.assertIn('document.getElementById("timer").textContent = "00:00";', start)
        self.assertNotIn("startTime = null", stop)


if __name__ == "__main__":
    unittest.main()
