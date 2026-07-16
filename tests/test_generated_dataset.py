import unittest
from pathlib import Path

from scripts.generated_dataset import validate_dataset


class RepositoryGeneratedDatasetTests(unittest.TestCase):
    def test_committed_dataset_matches_manifest(self):
        self.assertEqual(
            validate_dataset(
                Path("."),
                Path("tests/fixtures/generated_dataset_expectations.json"),
            ),
            [],
        )

    def test_old_mock_names_are_absent(self):
        for path in (
            "prompt/T2I/open.txt",
            "prompt/TI2I/open.txt",
            "ref_images/TI2I/open",
            "results/T2I/A",
            "results/T2I/B",
            "results/T2I/C",
            "results/TI2I/D",
            "results/TI2I/E",
        ):
            self.assertFalse(Path(path).exists(), path)
