import unittest

from app_core.errors import AppError
from app_core.model_catalog import compose_model_name, parse_model_name, validate_model_component


class ModelNameTests(unittest.TestCase):
    def test_composes_three_valid_components(self):
        self.assertEqual(
            compose_model_name("test", "Atlas", "default"),
            "test_Atlas_default",
        )

    def test_rejects_empty_underscore_and_unsafe_components(self):
        for value in ("", "   ", "foo_bar", ".", "..", "nested/path", "nested\\path"):
            with self.subTest(value=value):
                with self.assertRaises(AppError):
                    validate_model_component(value, "class")

    def test_parses_exactly_three_non_empty_parts(self):
        self.assertEqual(
            parse_model_name("test_Atlas_default"),
            {
                "class_name": "test",
                "model_name": "Atlas",
                "version": "default",
                "full_name": "test_Atlas_default",
            },
        )

    def test_preserves_non_standard_legacy_name(self):
        for full_name in ("Atlas", "too_many_parts_here", "broken__name"):
            with self.subTest(full_name=full_name):
                self.assertEqual(
                    parse_model_name(full_name),
                    {
                        "class_name": None,
                        "model_name": None,
                        "version": full_name,
                        "full_name": full_name,
                    },
                )


if __name__ == "__main__":
    unittest.main()
