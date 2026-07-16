import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.generated_dataset import (
    load_prompt,
    normalize_jpeg,
    render_contact_sheet,
    validate_dataset,
)


class GeneratedDatasetToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_image(
        self,
        relative_path: str,
        *,
        size: tuple[int, int] = (768, 768),
        mode: str = "RGB",
        image_format: str = "JPEG",
    ) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        color = (20, 80, 140) if mode == "RGB" else 128
        Image.new(mode, size, color).save(path, format=image_format)
        return path

    def build_valid_fixture(self) -> Path:
        prompt_files = {
            "prompt/T2I/portrait_anatomy.txt": "portrait_01\tA ceramic artist holding a mug.\n",
            "prompt/TI2I/object_edit.txt": "object_edit_01\tAdd one apple to the plate.\n",
        }
        for relative_path, contents in prompt_files.items():
            path = self.root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")

        self.write_image("results/T2I/Atlas/portrait_anatomy/portrait_01.jpg")
        self.write_image("ref_images/TI2I/object_edit/object_edit_01.jpg")
        self.write_image("results/TI2I/Mosaic/object_edit/object_edit_01.jpg")

        manifest = {
            "version": 1,
            "image": {"format": "JPEG", "mode": "RGB", "size": [768, 768]},
            "tasks": {
                "T2I": {
                    "Atlas": {
                        "portrait_anatomy": {
                            "portrait_01": {"tier": "high", "defect": "none"}
                        }
                    }
                },
                "TI2I": {
                    "Mosaic": {
                        "object_edit": {
                            "object_edit_01": {"tier": "high", "defect": "none"}
                        }
                    }
                },
            },
        }
        manifest_path = self.root / "expectations.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def test_load_prompt_parses_tab_separated_ids(self):
        prompt = self.root / "scene.txt"
        prompt.write_text("first\tFirst prompt.\nsecond\tSecond prompt.\n", encoding="utf-8")

        self.assertEqual(
            load_prompt(prompt),
            {"first": "First prompt.", "second": "Second prompt."},
        )

    def test_load_prompt_rejects_malformed_duplicate_and_empty_records(self):
        cases = {
            "missing-tab": "sample without a tab\n",
            "duplicate-id": "sample\tone\nsample\ttwo\n",
            "empty-id": "\tprompt\n",
            "empty-prompt": "sample\t\n",
            "blank-record": "sample\tprompt\n\n",
        }
        for name, contents in cases.items():
            with self.subTest(name=name):
                prompt = self.root / f"{name}.txt"
                prompt.write_text(contents, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_prompt(prompt)

    def test_normalize_jpeg_enforces_fixture_contract(self):
        source = self.root / "source.png"
        Image.new("RGBA", (640, 480), (20, 80, 140, 128)).save(source)
        destination = self.root / "normalized.jpg"

        normalize_jpeg(source, destination)

        with Image.open(destination) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (768, 768))
            self.assertFalse(image.getexif())

    def test_validator_accepts_matching_fixture(self):
        manifest = self.build_valid_fixture()

        self.assertEqual(validate_dataset(self.root, manifest), [])

    def test_validator_reports_missing_result_by_relative_path(self):
        manifest = self.build_valid_fixture()
        missing = self.root / "results/T2I/Atlas/portrait_anatomy/portrait_01.jpg"
        missing.unlink()

        errors = validate_dataset(self.root, manifest)

        self.assertIn(
            "missing results/T2I/Atlas/portrait_anatomy/portrait_01.jpg",
            errors,
        )

    def test_validator_reports_unexpected_result_by_relative_path(self):
        manifest = self.build_valid_fixture()
        self.write_image("results/T2I/Atlas/portrait_anatomy/portrait_02.jpg")

        errors = validate_dataset(self.root, manifest)

        self.assertIn(
            "unexpected results/T2I/Atlas/portrait_anatomy/portrait_02.jpg",
            errors,
        )

    def test_validator_reports_prompt_and_image_id_mismatch(self):
        manifest = self.build_valid_fixture()
        prompt = self.root / "prompt/T2I/portrait_anatomy.txt"
        prompt.write_text("portrait_02\tA different ID.\n", encoding="utf-8")

        errors = validate_dataset(self.root, manifest)

        self.assertIn(
            "ID mismatch prompt/T2I/portrait_anatomy.txt: missing portrait_01; unexpected portrait_02",
            errors,
        )

    def test_validator_reports_wrong_size_and_non_rgb_images(self):
        manifest = self.build_valid_fixture()
        wrong_size = self.root / "results/T2I/Atlas/portrait_anatomy/portrait_01.jpg"
        Image.new("RGB", (640, 768), "red").save(wrong_size, format="JPEG")
        non_rgb = self.root / "results/TI2I/Mosaic/object_edit/object_edit_01.jpg"
        Image.new("L", (768, 768), 128).save(non_rgb, format="PNG")

        errors = validate_dataset(self.root, manifest)

        self.assertIn(
            "invalid results/T2I/Atlas/portrait_anatomy/portrait_01.jpg: size 640x768, expected 768x768",
            errors,
        )
        self.assertIn(
            "invalid results/TI2I/Mosaic/object_edit/object_edit_01.jpg: format PNG, expected JPEG",
            errors,
        )
        self.assertIn(
            "invalid results/TI2I/Mosaic/object_edit/object_edit_01.jpg: mode L, expected RGB",
            errors,
        )

    def test_validator_reports_malformed_expectation_with_manifest_path(self):
        manifest_path = self.build_valid_fixture()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["tasks"]["T2I"]["Atlas"]["portrait_anatomy"]["portrait_01"] = {
            "tier": "excellent",
            "defect": "",
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        errors = validate_dataset(self.root, manifest_path)

        self.assertIn(
            "malformed expectation tasks/T2I/Atlas/portrait_anatomy/portrait_01",
            errors,
        )

    def test_validator_rejects_manifest_that_weakens_fixed_image_contract(self):
        manifest_path = self.build_valid_fixture()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["image"]["size"] = [640, 640]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        errors = validate_dataset(self.root, manifest_path)

        self.assertIn("malformed manifest image contract", errors)

    def test_validator_uses_separate_prompt_root_without_checking_images(self):
        manifest = self.build_valid_fixture()
        image_root = self.root / "staging"

        self.assertEqual(
            validate_dataset(
                image_root,
                manifest,
                check_images=False,
                prompt_root=self.root,
            ),
            [],
        )

    def test_contact_sheet_has_labeled_240_pixel_cells(self):
        first = self.write_image("inputs/one.jpg", size=(400, 200))
        second = self.write_image("inputs/two.jpg", size=(200, 400))
        destination = self.root / "sheet.jpg"

        render_contact_sheet(
            [("inputs/one.jpg", first), ("inputs/two.jpg", second)],
            destination,
            columns=2,
        )

        with Image.open(destination) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.width, 480)
            self.assertGreater(image.height, 240)


if __name__ == "__main__":
    unittest.main()
