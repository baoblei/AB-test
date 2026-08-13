import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_core.config import DIM_LABELS, TASK_CONFIGS
from app_core.database import init_db
from app_core.schemas import VoteSubmit

try:
    from app_core.dimensions import canonical_selected_dimensions, dimension_transition
except ImportError:
    canonical_selected_dimensions = None
    dimension_transition = None


class VideoConfigTests(unittest.TestCase):
    def test_video_task_capabilities_and_dimension_order(self):
        expected_t2v_dashboard = [
            "overall",
            "text_consistency",
            "structure_reasonableness",
            "motion_reasonableness",
            "dynamism",
            "physical_plausibility",
            "visual_quality",
        ]
        expected_t2v_eval = expected_t2v_dashboard[1:]
        expected_ti2v_dashboard = expected_t2v_dashboard + ["image_consistency"]
        expected_ti2v_eval = expected_t2v_eval + ["image_consistency"]

        self.assertIn("T2V", TASK_CONFIGS)
        self.assertIn("TI2V", TASK_CONFIGS)
        self.assertEqual(TASK_CONFIGS["T2V"]["media_type"], "video")
        self.assertEqual(TASK_CONFIGS["TI2V"]["result_extensions"], (".mp4", ".webm"))
        self.assertFalse(TASK_CONFIGS["T2V"]["upload_has_ref"])
        self.assertTrue(TASK_CONFIGS["TI2V"]["upload_has_ref"])
        self.assertEqual(TASK_CONFIGS["T2V"]["eval_dims"], expected_t2v_eval)
        self.assertEqual(TASK_CONFIGS["T2V"]["dashboard_dims"], expected_t2v_dashboard)
        self.assertEqual(TASK_CONFIGS["TI2V"]["eval_dims"], expected_ti2v_eval)
        self.assertEqual(TASK_CONFIGS["TI2V"]["dashboard_dims"], expected_ti2v_dashboard)
        self.assertEqual(DIM_LABELS["structure_reasonableness"], "结构合理性")
        self.assertIn("structure_reasonableness", VoteSubmit.model_fields)
        self.assertEqual(TASK_CONFIGS["T2I"]["media_type"], "image")

    def test_dimension_selection_is_validated_and_canonicalized(self):
        self.assertIsNotNone(canonical_selected_dimensions)
        self.assertEqual(
            canonical_selected_dimensions("T2V", ["dynamism", "overall"]),
            ["overall", "dynamism"],
        )
        for values in ([], ["overall", "overall"], ["fidelity"]):
            with self.subTest(values=values), self.assertRaises(Exception):
                canonical_selected_dimensions("T2V", values)

    def test_dimension_transition_uses_set_inclusion(self):
        self.assertIsNotNone(dimension_transition)
        self.assertEqual(dimension_transition(["overall"], ["overall"]), "equal")
        self.assertEqual(
            dimension_transition(["overall"], ["overall", "dynamism"]),
            "superset",
        )
        self.assertEqual(
            dimension_transition(["overall", "dynamism"], ["overall"]),
            "subset",
        )
        self.assertEqual(
            dimension_transition(["overall"], ["dynamism"]),
            "incomparable",
        )


class VideoSchemaTests(unittest.TestCase):
    def test_init_db_adds_video_scores_and_scope_table_idempotently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "test.db"
            with patch("app_core.database.DB_PATH", str(database)):
                init_db()
                init_db()
            conn = sqlite3.connect(database)
            result_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(results_log)")
            }
            scope_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(evaluation_scopes)")
            }
            indexes = {
                row[1] for row in conn.execute("PRAGMA index_list(evaluation_scopes)")
            }
            conn.close()

        self.assertTrue(
            {
                "text_consistency",
                "structure_reasonableness",
                "motion_reasonableness",
                "dynamism",
                "physical_plausibility",
                "visual_quality",
                "image_consistency",
                "selected_dimensions",
            }.issubset(result_columns)
        )
        self.assertTrue(
            {
                "user_id",
                "task_type",
                "v_a",
                "v_b",
                "scene",
                "selected_dimensions",
            }.issubset(scope_columns)
        )
        self.assertIn("idx_evaluation_scopes_unique", indexes)


if __name__ == "__main__":
    unittest.main()
