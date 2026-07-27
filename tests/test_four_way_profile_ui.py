import unittest
from pathlib import Path


class FourWayProfileUiTests(unittest.TestCase):
    def test_profile_maps_both_tie_subtypes_without_generic_tie(self):
        html = Path("templates/profile.html").read_text(encoding="utf-8")
        self.assertIn("r.overall === 'tie_bad'", html)
        self.assertIn("一样差", html)
        self.assertIn("r.overall === 'tie_good'", html)
        self.assertIn("一样好", html)
        self.assertNotIn("r.overall === 'tie'", html)
