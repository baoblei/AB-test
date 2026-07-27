import unittest
from pathlib import Path


class FourWayEvaluationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/index.html").read_text(encoding="utf-8")

    def function_source(self, name, next_name):
        start = self.html.index(f"function {name}")
        return self.html[start:self.html.index(f"function {next_name}", start)]

    def test_full_mode_includes_explicit_overall_dimension(self):
        source = self.function_source("getActiveEvalDims", "handleEvalModeChange")
        self.assertIn('[{ key: "overall", label: "整体" }, ...state.config.eval_dims]', source)

    def test_evaluation_table_has_four_ordered_choices(self):
        source = self.function_source("renderEvalTable", "previewToolIcon")
        for value in ("left", "tie_bad", "tie_good", "right"):
            self.assertIn(value, source)
        positions = [source.index(label) for label in ("A 好", "一样差", "一样好", "B 好")]
        self.assertEqual(positions, sorted(positions))

    def test_ti2i_main_and_lightbox_put_reference_between_candidates(self):
        main = self.function_source("renderCompareGrid", "renderImageCard")
        lightbox = self.function_source("renderLightbox", "renderLightboxPane")
        self.assertLess(main.index('renderImageCard("left"'), main.index('renderImageCard("reference"'))
        self.assertLess(main.index('renderImageCard("reference"'), main.index('renderImageCard("right"'))
        self.assertLess(lightbox.index('side: "left"'), lightbox.index('side: "reference"'))
        self.assertLess(lightbox.index('side: "reference"'), lightbox.index('side: "right"'))
