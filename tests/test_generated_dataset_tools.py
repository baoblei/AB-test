import json
from collections import Counter
from io import BytesIO
import inspect
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import scripts.generated_dataset as generated_dataset
from scripts.generated_dataset import (
    load_prompt,
    normalize_jpeg,
    render_contact_sheet,
    validate_dataset,
)


class GeneratedDatasetToolTests(unittest.TestCase):
    SCENES = {
        "T2I": ("portrait_anatomy", "text_product", "spatial_composition"),
        "TI2I": ("object_edit", "appearance_edit", "background_style"),
    }
    MODELS = {
        "T2I": ("Atlas", "Beacon", "Cipher"),
        "TI2I": ("Mosaic", "Prism"),
    }
    TIERS = {
        "Atlas": ("high", "high", "high", "high", "high", "medium"),
        "Beacon": ("high", "high", "medium", "medium", "medium", "weak"),
        "Cipher": ("medium", "weak", "weak", "weak", "weak", "weak"),
        "Mosaic": ("high", "high", "high", "high", "high", "medium"),
        "Prism": ("medium", "medium", "weak", "weak", "weak", "weak"),
    }

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        buffer = BytesIO()
        Image.new("RGB", (768, 768), (20, 80, 140)).save(
            buffer, format="JPEG", quality=85, optimize=True
        )
        self.valid_jpeg = buffer.getvalue()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_image(
        self,
        relative_path: str,
        *,
        size: tuple[int, int] = (768, 768),
        mode: str = "RGB",
        image_format: str = "JPEG",
        quality: int = 85,
        **save_options,
    ) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        color = (20, 80, 140) if mode == "RGB" else 128
        Image.new(mode, size, color).save(
            path, format=image_format, quality=quality, **save_options
        )
        return path

    def write_valid_image(self, relative_path: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.valid_jpeg)
        return path

    def build_valid_fixture(self) -> Path:
        manifest = {
            "version": 1,
            "image": {
                "format": "JPEG",
                "mode": "RGB",
                "size": [768, 768],
                "quality": 85,
            },
            "tasks": {"T2I": {}, "TI2I": {}},
        }
        for task, scenes in self.SCENES.items():
            scene_ids = {}
            for scene in scenes:
                prefix = {
                    "portrait_anatomy": "portrait",
                    "text_product": "text",
                    "spatial_composition": "spatial",
                    "object_edit": "object_edit",
                    "appearance_edit": "appearance",
                    "background_style": "background",
                }[scene]
                sample_ids = tuple(f"{prefix}_{index:02d}" for index in range(1, 7))
                scene_ids[scene] = sample_ids
                prompt = self.root / f"prompt/{task}/{scene}.txt"
                prompt.parent.mkdir(parents=True, exist_ok=True)
                prompt.write_text(
                    "".join(f"{sample_id}\tPrompt for {sample_id}.\n" for sample_id in sample_ids),
                    encoding="utf-8",
                )
                if task == "TI2I":
                    for sample_id in sample_ids:
                        self.write_valid_image(f"ref_images/TI2I/{scene}/{sample_id}.jpg")

            for model in self.MODELS[task]:
                manifest["tasks"][task][model] = {}
                for scene, sample_ids in scene_ids.items():
                    manifest["tasks"][task][model][scene] = {}
                    for sample_id, tier in zip(sample_ids, self.TIERS[model]):
                        manifest["tasks"][task][model][scene][sample_id] = {
                            "tier": tier,
                            "defect": "none" if tier == "high" else "localized detail defect",
                        }
                        self.write_valid_image(
                            f"results/{task}/{model}/{scene}/{sample_id}.jpg"
                        )

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
        self.write_image("results/T2I/Atlas/portrait_anatomy/portrait_07.jpg")

        errors = validate_dataset(self.root, manifest)

        self.assertIn(
            "unexpected results/T2I/Atlas/portrait_anatomy/portrait_07.jpg",
            errors,
        )

    def test_validator_reports_prompt_and_image_id_mismatch(self):
        manifest = self.build_valid_fixture()
        prompt = self.root / "prompt/T2I/portrait_anatomy.txt"
        prompt.write_text(
            "portrait_07\tA different ID.\n"
            + "".join(
                f"portrait_{index:02d}\tPrompt for portrait_{index:02d}.\n"
                for index in range(2, 7)
            ),
            encoding="utf-8",
        )

        errors = validate_dataset(self.root, manifest)

        self.assertIn(
            "ID mismatch prompt/T2I/portrait_anatomy.txt: missing portrait_01; unexpected portrait_07",
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

    def test_validator_enforces_canonical_models_scenes_and_totals(self):
        manifest_path = self.build_valid_fixture()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["tasks"]["T2I"]["Rogue"] = manifest["tasks"]["T2I"].pop("Atlas")
        manifest["tasks"]["TI2I"]["Mosaic"]["rogue_scene"] = (
            manifest["tasks"]["TI2I"]["Mosaic"].pop("background_style")
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        errors = validate_dataset(self.root, manifest_path, check_images=False)

        self.assertIn(
            "invalid models tasks/T2I: expected Atlas, Beacon, Cipher; got Beacon, Cipher, Rogue",
            errors,
        )
        self.assertIn(
            "invalid scenes tasks/TI2I/Mosaic: expected appearance_edit, background_style, object_edit; "
            "got appearance_edit, object_edit, rogue_scene",
            errors,
        )

    def test_validator_enforces_final_dataset_totals(self):
        manifest_path = self.build_valid_fixture()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["tasks"]["T2I"]["Atlas"]["portrait_anatomy"]["portrait_01"]
        for model in self.MODELS["TI2I"]:
            del manifest["tasks"]["TI2I"][model]["object_edit"]["object_edit_01"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        errors = validate_dataset(self.root, manifest_path, check_images=False)

        self.assertIn("invalid output total tasks/T2I: expected 54, got 53", errors)
        self.assertIn("invalid reference total tasks/TI2I: expected 18, got 17", errors)
        self.assertIn("invalid output total tasks/TI2I: expected 36, got 34", errors)

    def test_validator_enforces_manifest_quality_85(self):
        manifest_path = self.build_valid_fixture()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["image"]["quality"] = 75
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        errors = validate_dataset(self.root, manifest_path, check_images=False)

        self.assertIn("malformed manifest image contract", errors)

    def test_validator_rejects_jpeg_not_encoded_at_quality_85(self):
        manifest = self.build_valid_fixture()
        path = self.root / "results/T2I/Atlas/portrait_anatomy/portrait_01.jpg"
        Image.new("RGB", (768, 768), "red").save(path, format="JPEG", quality=75)

        errors = validate_dataset(self.root, manifest)

        self.assertIn(
            "invalid results/T2I/Atlas/portrait_anatomy/portrait_01.jpg: "
            "JPEG quantization does not match quality 85",
            errors,
        )

    def test_validator_rejects_all_pillow_image_metadata(self):
        manifest = self.build_valid_fixture()
        path = self.root / "results/T2I/Atlas/portrait_anatomy/portrait_01.jpg"
        self.write_image(
            "results/T2I/Atlas/portrait_anatomy/portrait_01.jpg",
            icc_profile=b"fake-icc",
            xmp=b"<x:xmpmeta/>",
            comment=b"generated fixture",
        )

        errors = validate_dataset(self.root, manifest)

        self.assertIn(
            "invalid results/T2I/Atlas/portrait_anatomy/portrait_01.jpg: "
            "metadata present (comment, icc_profile, xmp)",
            errors,
        )

    def test_validator_recursively_rejects_every_unexpected_prompt_tree_file(self):
        manifest = self.build_valid_fixture()
        unexpected = (
            "prompt/T2I/nested/rogue.txt",
            "prompt/TI2I/notes.md",
            "prompt/rogue.txt",
            "prompt/Unknown/rogue.txt",
        )
        for relative_path in unexpected:
            path = self.root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unexpected", encoding="utf-8")

        errors = validate_dataset(self.root, manifest, check_images=False)

        for relative_path in unexpected:
            with self.subTest(relative_path=relative_path):
                self.assertIn(f"unexpected {relative_path}", errors)

    def test_validator_rejects_dpi_and_progressive_jpeg_attributes(self):
        manifest = self.build_valid_fixture()
        relative_path = "results/T2I/Atlas/portrait_anatomy/portrait_01.jpg"
        cases = {
            "dpi": ({"dpi": (300, 300)}, "metadata present (dpi)"),
            "progressive": (
                {"progressive": True},
                "metadata present (progression, progressive)",
            ),
        }
        for name, (save_options, expected) in cases.items():
            with self.subTest(name=name):
                self.write_image(relative_path, **save_options)

                errors = validate_dataset(self.root, manifest)

                self.assertIn(f"invalid {relative_path}: {expected}", errors)
                self.write_valid_image(relative_path)

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

    def test_contact_sheet_supports_larger_review_thumbnails(self):
        self.assertIn("thumbnail_size", inspect.signature(render_contact_sheet).parameters)
        first = self.write_image("inputs/one.jpg", size=(400, 200))
        second = self.write_image("inputs/two.jpg", size=(200, 400))
        destination = self.root / "review-sheet.jpg"

        render_contact_sheet(
            [("one.jpg", first), ("two.jpg", second)],
            destination,
            columns=2,
            thumbnail_size=420,
        )

        with Image.open(destination) as image:
            self.assertEqual(image.width, 840)
            self.assertGreater(image.height, 420)

    def test_short_contact_sheet_labels_keep_review_identity(self):
        self.assertTrue(hasattr(generated_dataset, "_short_contact_sheet_label"))
        cases = {
            "results/TI2I/Prism/object_edit/object_edit_01.jpg": (
                "Prism/object_edit/object_edit_01.jpg"
            ),
            "ref_images/TI2I/object_edit/object_edit_01.jpg": (
                "reference/object_edit/object_edit_01.jpg"
            ),
        }
        draw = ImageDraw.Draw(Image.new("RGB", (420, 44), "white"))
        for full_label, expected in cases.items():
            with self.subTest(full_label=full_label):
                short_label = generated_dataset._short_contact_sheet_label(full_label)
                self.assertEqual(short_label, expected)
                self.assertLessEqual(draw.textbbox((0, 0), short_label)[2], 412)

    def test_contact_sheet_cli_accepts_short_labels_and_thumbnail_size(self):
        contact_parser = next(
            action.choices["contact-sheet"]
            for action in generated_dataset._build_parser()._actions
            if getattr(action, "choices", None) and "contact-sheet" in action.choices
        )
        option_strings = {
            option
            for action in contact_parser._actions
            for option in action.option_strings
        }
        self.assertIn("--short-labels", option_strings)
        self.assertIn("--thumbnail-size", option_strings)

        args = generated_dataset._build_parser().parse_args(
            [
                "contact-sheet",
                "pilot",
                "pilot-sheet.jpg",
                "--short-labels",
                "--thumbnail-size",
                "420",
            ]
        )

        self.assertTrue(args.short_labels)
        self.assertEqual(args.thumbnail_size, 420)


class GeneratedDatasetRepositoryContractTests(unittest.TestCase):
    def test_repository_manifest_has_expected_shape(self):
        manifest_path = Path("tests/fixtures/generated_dataset_expectations.json")
        errors = validate_dataset(Path("."), manifest_path, check_images=False)
        self.assertEqual(errors, [])

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_scenes = {
            "T2I": {"portrait_anatomy", "text_product", "spatial_composition"},
            "TI2I": {"object_edit", "appearance_edit", "background_style"},
        }
        expected_ids = {
            "portrait_anatomy": {f"portrait_{index:02d}" for index in range(1, 7)},
            "text_product": {f"text_{index:02d}" for index in range(1, 7)},
            "spatial_composition": {f"spatial_{index:02d}" for index in range(1, 7)},
            "object_edit": {f"object_edit_{index:02d}" for index in range(1, 7)},
            "appearance_edit": {f"appearance_{index:02d}" for index in range(1, 7)},
            "background_style": {f"background_{index:02d}" for index in range(1, 7)},
        }
        expected_profiles = {
            "Atlas": Counter({"high": 5, "medium": 1}),
            "Beacon": Counter({"high": 2, "medium": 3, "weak": 1}),
            "Cipher": Counter({"medium": 1, "weak": 5}),
            "Mosaic": Counter({"high": 5, "medium": 1}),
            "Prism": Counter({"medium": 2, "weak": 4}),
        }
        self.assertEqual(set(manifest["tasks"]), {"T2I", "TI2I"})
        self.assertEqual(set(manifest["tasks"]["T2I"]), {"Atlas", "Beacon", "Cipher"})
        self.assertEqual(set(manifest["tasks"]["TI2I"]), {"Mosaic", "Prism"})
        for task, models in manifest["tasks"].items():
            for model, scenes in models.items():
                with self.subTest(task=task, model=model):
                    self.assertEqual(set(scenes), expected_scenes[task])
                for scene, samples in scenes.items():
                    with self.subTest(task=task, model=model, scene=scene):
                        self.assertEqual(set(samples), expected_ids[scene])
                        self.assertEqual(
                            Counter(expectation["tier"] for expectation in samples.values()),
                            expected_profiles[model],
                        )


if __name__ == "__main__":
    unittest.main()
