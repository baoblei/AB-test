import asyncio
import unittest
from pathlib import Path

import main


class UserHelpPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = Path("templates/dashboard.html").read_text(encoding="utf-8")
        cls.readme = Path("README.md").read_text(encoding="utf-8")

    def test_dashboard_top_navigation_links_to_user_help(self):
        navbar = self.dashboard.split('<div class="navbar">', 1)[1].split(
            "</div>\n        </div>", 1
        )[0]
        self.assertIn('class="help-link"', navbar)
        self.assertIn('href="/help"', navbar)
        self.assertIn("使用帮助", navbar)

    def test_help_route_returns_the_user_facing_guide(self):
        response = asyncio.run(main.help_page())
        self.assertIn("平台使用说明", response)
        self.assertIn("统计指标计算口径", response)

    def test_help_guide_defines_every_dashboard_statistic_and_ambiguous_count(self):
        help_html = Path("templates/help.html").read_text(encoding="utf-8")
        for marker in (
            "有效评测记录",
            "去重样例",
            "多人共同评价",
            "A 胜 / B 胜",
            "一样差 / 一样好",
            "A 压制 / B 压制",
            "冲突宽容度",
            "并集冲突比例",
            "交集冲突比例",
            "统计时去除冲突项",
            "坏例占比",
            "高频坏例",
            "排行榜胜率",
            "评测员统计",
            "个人统计",
            "管理后台统计",
        ):
            self.assertIn(marker, help_html)

        for formula in (
            "A 压制 =（A 胜 + 一样差 + 一样好）÷（B 胜 + 一样差 + 一样好）",
            "少数方占比 = min(A 票人数, B 票人数) ÷ (A 票人数 + B 票人数)",
            "坏例占比 = 至少包含一个坏例标签的评测记录数 ÷ 该模型侧评测记录总数",
            "排行榜胜率 = 胜场数 ÷ 对战数",
        ):
            self.assertIn(formula, help_html)

        self.assertIn("50 + 50 - 9 = 91", help_html)
        self.assertIn("交集冲突比例 = 冲突样例数 ÷ 多人共同评价样例数", help_html)
        self.assertIn("1/91", help_html)
        self.assertIn("1/9", help_html)
        self.assertNotIn("pip install", help_html)
        self.assertNotIn("uvicorn", help_html)

    def test_readme_links_help_page_and_matches_conflict_denominator_definition(self):
        for marker in (
            "`/help`：用户侧平台使用说明",
            "并集冲突比例",
            "交集冲突比例",
            "评测记录数",
            "去重样例并集数",
            "多人共同评价样例数",
            "50 + 50 - 9 = 91",
            "交集冲突比例 = 冲突样例数 ÷ 多人共同评价样例数",
        ):
            self.assertIn(marker, self.readme)


if __name__ == "__main__":
    unittest.main()
