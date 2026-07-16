from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageOps


IMAGE_SIZE = (768, 768)
IMAGE_QUALITY = 85
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VALID_TIERS = {"high", "medium", "weak"}
SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
GENERIC_DEFECTS = {"bad", "bad quality", "low quality", "none"}
QUALITY_PROFILES = {
    "T2I": {
        "Atlas": Counter({"high": 5, "medium": 1}),
        "Beacon": Counter({"high": 2, "medium": 3, "weak": 1}),
        "Cipher": Counter({"medium": 1, "weak": 5}),
    },
    "TI2I": {
        "Mosaic": Counter({"high": 5, "medium": 1}),
        "Prism": Counter({"medium": 2, "weak": 4}),
    },
}
CANONICAL_SCENES = {
    "T2I": ("portrait_anatomy", "text_product", "spatial_composition"),
    "TI2I": ("object_edit", "appearance_edit", "background_style"),
}
EXPECTED_OUTPUT_TOTALS = {"T2I": 54, "TI2I": 36}
EXPECTED_REFERENCE_TOTAL = 18
JPEG_STRUCTURAL_INFO = {
    "jfif",
    "jfif_version",
    "jfif_unit",
    "jfif_density",
}


def _quality_85_quantization() -> dict[int, tuple[int, ...]]:
    buffer = BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, "JPEG", quality=IMAGE_QUALITY)
    buffer.seek(0)
    with Image.open(buffer) as image:
        return {table_id: tuple(values) for table_id, values in image.quantization.items()}


QUALITY_85_QUANTIZATION = _quality_85_quantization()


def load_prompt(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"{path}: prompt file is empty")
    for line_number, line in enumerate(lines, start=1):
        if not line or line.count("\t") != 1:
            raise ValueError(f"{path}:{line_number}: expected one tab-separated record")
        sample_id, prompt = line.split("\t")
        if not SAFE_COMPONENT.fullmatch(sample_id):
            raise ValueError(f"{path}:{line_number}: invalid sample ID {sample_id!r}")
        if not prompt or prompt != prompt.strip():
            raise ValueError(f"{path}:{line_number}: prompt must be non-empty and trimmed")
        if sample_id in records:
            raise ValueError(f"{path}:{line_number}: duplicate sample ID {sample_id!r}")
        records[sample_id] = prompt
    return records


def normalize_jpeg(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as original:
        image = ImageOps.fit(
            original.convert("RGB"),
            IMAGE_SIZE,
            method=Image.Resampling.LANCZOS,
        )
        image.save(destination, "JPEG", quality=IMAGE_QUALITY, optimize=True, exif=b"")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _expected_image_contract(manifest: dict[str, Any], errors: list[str]) -> tuple[str, str, tuple[int, int]]:
    image = manifest.get("image")
    if not isinstance(image, dict):
        errors.append("malformed manifest image contract")
        return "JPEG", "RGB", IMAGE_SIZE
    image_format = image.get("format")
    mode = image.get("mode")
    size = image.get("size")
    quality = image.get("quality")
    if size is None and isinstance(image.get("width"), int) and isinstance(image.get("height"), int):
        size = [image["width"], image["height"]]
    if (
        not isinstance(image_format, str)
        or not isinstance(mode, str)
        or not isinstance(size, list)
        or len(size) != 2
        or not all(isinstance(value, int) and value > 0 for value in size)
        or image_format.upper() != "JPEG"
        or mode != "RGB"
        or size != list(IMAGE_SIZE)
        or quality != IMAGE_QUALITY
    ):
        errors.append("malformed manifest image contract")
        return "JPEG", "RGB", IMAGE_SIZE
    return "JPEG", "RGB", IMAGE_SIZE


def _load_manifest(manifest_path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid manifest {manifest_path}: {exc}")
        return None
    if not isinstance(manifest, dict):
        errors.append("malformed manifest root")
        return None
    if not isinstance(manifest.get("version"), int):
        errors.append("malformed manifest version")
    return manifest


def _parse_expectations(
    manifest: dict[str, Any], errors: list[str]
) -> tuple[dict[str, dict[str, dict[str, dict[str, dict[str, str]]]]], set[str]]:
    tasks = manifest.get("tasks")
    if not isinstance(tasks, dict) or set(tasks) != {"T2I", "TI2I"}:
        errors.append("malformed manifest tasks: expected T2I and TI2I")
        return {}, set()

    parsed: dict[str, dict[str, dict[str, dict[str, dict[str, str]]]]] = {}
    expected_results: set[str] = set()
    for task in ("T2I", "TI2I"):
        models = tasks.get(task)
        if not isinstance(models, dict) or not models:
            errors.append(f"malformed manifest tasks/{task}")
            parsed[task] = {}
            continue
        parsed[task] = {}
        for model, scenes in models.items():
            model_path = f"tasks/{task}/{model}"
            if not isinstance(model, str) or not SAFE_COMPONENT.fullmatch(model) or not isinstance(scenes, dict) or not scenes:
                errors.append(f"malformed manifest {model_path}")
                continue
            parsed[task][model] = {}
            for scene, samples in scenes.items():
                scene_path = f"{model_path}/{scene}"
                if not isinstance(scene, str) or not SAFE_COMPONENT.fullmatch(scene) or not isinstance(samples, dict) or not samples:
                    errors.append(f"malformed manifest {scene_path}")
                    continue
                parsed[task][model][scene] = {}
                for sample_id, expectation in samples.items():
                    expectation_path = f"{scene_path}/{sample_id}"
                    valid_name = isinstance(sample_id, str) and SAFE_COMPONENT.fullmatch(sample_id)
                    valid_expectation = (
                        isinstance(expectation, dict)
                        and set(expectation) == {"tier", "defect"}
                        and expectation.get("tier") in VALID_TIERS
                        and isinstance(expectation.get("defect"), str)
                        and expectation["defect"] == expectation["defect"].strip()
                        and bool(expectation["defect"])
                        and (
                            (expectation["tier"] == "high" and expectation["defect"] == "none")
                            or (
                                expectation["tier"] != "high"
                                and expectation["defect"].casefold() not in GENERIC_DEFECTS
                            )
                        )
                    )
                    if not valid_name or not valid_expectation:
                        errors.append(f"malformed expectation {expectation_path}")
                    if valid_name:
                        parsed[task][model][scene][sample_id] = expectation if isinstance(expectation, dict) else {}
                        expected_results.add(f"results/{task}/{model}/{scene}/{sample_id}.jpg")
    return parsed, expected_results


def _scene_ids(
    models: dict[str, dict[str, dict[str, dict[str, str]]]]
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for scenes in models.values():
        for scene, samples in scenes.items():
            result.setdefault(scene, set()).update(samples)
    return result


def _format_id_mismatch(relative_path: str, missing: set[str], unexpected: set[str]) -> str:
    details = []
    if missing:
        details.append(f"missing {', '.join(sorted(missing))}")
    if unexpected:
        details.append(f"unexpected {', '.join(sorted(unexpected))}")
    return f"ID mismatch {relative_path}: {'; '.join(details)}"


def _validate_prompt_contract(
    prompt_root: Path,
    parsed: dict[str, dict[str, dict[str, dict[str, dict[str, str]]]]],
    errors: list[str],
) -> None:
    prompt_tree_root = prompt_root / "prompt"
    actual_prompt_files = _all_files(prompt_tree_root)
    expected_prompt_files_by_task = {
        task: {
            prompt_tree_root / task / f"{scene}.txt"
            for scene in _scene_ids(parsed.get(task, {}))
        }
        for task in ("T2I", "TI2I")
    }
    expected_prompt_files = set().union(*expected_prompt_files_by_task.values())
    for path in sorted(expected_prompt_files - actual_prompt_files):
        errors.append(f"missing {_relative(path, prompt_root)}")
    for path in sorted(actual_prompt_files - expected_prompt_files):
        errors.append(f"unexpected {_relative(path, prompt_root)}")

    for task in ("T2I", "TI2I"):
        expected_scenes = _scene_ids(parsed.get(task, {}))
        for path in sorted(actual_prompt_files & expected_prompt_files_by_task[task]):
            try:
                prompt_ids = set(load_prompt(path))
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append(f"invalid {_relative(path, prompt_root)}: {exc}")
                continue
            scene = path.stem
            expected_ids = expected_scenes[scene]
            if prompt_ids != expected_ids:
                errors.append(
                    _format_id_mismatch(
                        _relative(path, prompt_root),
                        expected_ids - prompt_ids,
                        prompt_ids - expected_ids,
                    )
                )

        for model, scenes in parsed.get(task, {}).items():
            for scene, expected_ids in expected_scenes.items():
                model_ids = set(scenes.get(scene, {}))
                if model_ids != expected_ids:
                    errors.append(
                        _format_id_mismatch(
                            f"tasks/{task}/{model}/{scene}",
                            expected_ids - model_ids,
                            model_ids - expected_ids,
                        )
                    )


def _validate_quality_profiles(
    parsed: dict[str, dict[str, dict[str, dict[str, dict[str, str]]]]],
    errors: list[str],
) -> None:
    for task, profiles in QUALITY_PROFILES.items():
        models = parsed.get(task, {})
        if set(models) != set(profiles):
            continue
        for model, expected_counts in profiles.items():
            for scene, samples in models[model].items():
                if len(samples) != 6:
                    errors.append(f"invalid tier totals tasks/{task}/{model}/{scene}: expected 6 entries")
                    continue
                actual_counts = Counter(
                    expectation.get("tier")
                    for expectation in samples.values()
                    if isinstance(expectation, dict)
                )
                if actual_counts != expected_counts:
                    errors.append(
                        f"invalid tier totals tasks/{task}/{model}/{scene}: "
                        f"expected {dict(expected_counts)}, got {dict(actual_counts)}"
                    )


def _validate_canonical_shape(
    parsed: dict[str, dict[str, dict[str, dict[str, dict[str, str]]]]],
    errors: list[str],
) -> None:
    for task in ("T2I", "TI2I"):
        models = parsed.get(task, {})
        expected_models = set(QUALITY_PROFILES[task])
        actual_models = set(models)
        if actual_models != expected_models:
            errors.append(
                f"invalid models tasks/{task}: expected {', '.join(sorted(expected_models))}; "
                f"got {', '.join(sorted(actual_models))}"
            )

        expected_scenes = set(CANONICAL_SCENES[task])
        for model, scenes in models.items():
            actual_scenes = set(scenes)
            if actual_scenes != expected_scenes:
                errors.append(
                    f"invalid scenes tasks/{task}/{model}: "
                    f"expected {', '.join(sorted(expected_scenes))}; "
                    f"got {', '.join(sorted(actual_scenes))}"
                )

        output_total = sum(
            len(samples)
            for scenes in models.values()
            for samples in scenes.values()
        )
        expected_output_total = EXPECTED_OUTPUT_TOTALS[task]
        if output_total != expected_output_total:
            errors.append(
                f"invalid output total tasks/{task}: expected {expected_output_total}, "
                f"got {output_total}"
            )

    reference_total = sum(
        len(sample_ids) for sample_ids in _scene_ids(parsed.get("TI2I", {})).values()
    )
    if reference_total != EXPECTED_REFERENCE_TOTAL:
        errors.append(
            f"invalid reference total tasks/TI2I: expected {EXPECTED_REFERENCE_TOTAL}, "
            f"got {reference_total}"
        )


def _all_files(root: Path) -> set[Path]:
    return {path for path in root.rglob("*") if path.is_file()} if root.is_dir() else set()


def _validate_image(path: Path, relative_path: str, contract: tuple[str, str, tuple[int, int]], errors: list[str]) -> None:
    expected_format, expected_mode, expected_size = contract
    try:
        with Image.open(path) as image:
            image.load()
            if image.format != expected_format:
                errors.append(f"invalid {relative_path}: format {image.format}, expected {expected_format}")
            if image.mode != expected_mode:
                errors.append(f"invalid {relative_path}: mode {image.mode}, expected {expected_mode}")
            if image.size != expected_size:
                errors.append(
                    f"invalid {relative_path}: size {image.width}x{image.height}, "
                    f"expected {expected_size[0]}x{expected_size[1]}"
                )
            if image.getexif():
                errors.append(f"invalid {relative_path}: EXIF metadata present")
            metadata_keys = sorted(set(image.info) - JPEG_STRUCTURAL_INFO)
            if metadata_keys:
                errors.append(
                    f"invalid {relative_path}: metadata present ({', '.join(metadata_keys)})"
                )
            quantization = {
                table_id: tuple(values)
                for table_id, values in getattr(image, "quantization", {}).items()
            }
            if image.format == "JPEG" and quantization != QUALITY_85_QUANTIZATION:
                errors.append(
                    f"invalid {relative_path}: JPEG quantization does not match quality 85"
                )
    except (OSError, ValueError) as exc:
        errors.append(f"invalid {relative_path}: unreadable image ({exc})")


def validate_dataset(
    repo_root: Path,
    manifest_path: Path,
    *,
    check_images: bool = True,
    prompt_root: Path | None = None,
) -> list[str]:
    repo_root = Path(repo_root)
    prompt_root = Path(prompt_root) if prompt_root is not None else repo_root
    errors: list[str] = []
    manifest = _load_manifest(Path(manifest_path), errors)
    if manifest is None:
        return errors
    image_contract = _expected_image_contract(manifest, errors)
    parsed, expected_results = _parse_expectations(manifest, errors)
    _validate_canonical_shape(parsed, errors)
    _validate_prompt_contract(prompt_root, parsed, errors)
    _validate_quality_profiles(parsed, errors)
    if not check_images:
        return errors

    expected_references = {
        f"ref_images/TI2I/{scene}/{sample_id}.jpg"
        for scene, sample_ids in _scene_ids(parsed.get("TI2I", {})).items()
        for sample_id in sample_ids
    }
    expected_images = expected_results | expected_references
    actual_images = {
        _relative(path, repo_root)
        for data_root in (repo_root / "results", repo_root / "ref_images")
        for path in _all_files(data_root)
    }
    for relative_path in sorted(expected_images - actual_images):
        errors.append(f"missing {relative_path}")
    for relative_path in sorted(actual_images - expected_images):
        errors.append(f"unexpected {relative_path}")
    for relative_path in sorted(expected_images & actual_images):
        _validate_image(repo_root / relative_path, relative_path, image_contract, errors)
    return errors


def render_contact_sheet(
    entries: list[tuple[str, Path]], destination: Path, columns: int = 3
) -> None:
    if columns < 1:
        raise ValueError("columns must be at least 1")
    if not entries:
        raise ValueError("at least one image is required")
    thumbnail_size = 240
    label_height = 44
    rows = (len(entries) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumbnail_size, rows * (thumbnail_size + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, path) in enumerate(entries):
        column = index % columns
        row = index // columns
        left = column * thumbnail_size
        top = row * (thumbnail_size + label_height)
        with Image.open(path) as source:
            thumbnail = ImageOps.contain(
                source.convert("RGB"),
                (thumbnail_size, thumbnail_size),
                method=Image.Resampling.LANCZOS,
            )
        image_left = left + (thumbnail_size - thumbnail.width) // 2
        image_top = top + (thumbnail_size - thumbnail.height) // 2
        sheet.paste(thumbnail, (image_left, image_top))
        draw.text((left + 4, top + thumbnail_size + 4), label, fill="black")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, "JPEG", quality=85, optimize=True, exif=b"")


def _discover_images(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in SUPPORTED_IMAGE_SUFFIXES
    )


def _normalize_tree(root: Path) -> int:
    paths = _discover_images(root)
    for path in paths:
        temporary_path = path.with_name(f".{path.name}.normalized.tmp")
        try:
            normalize_jpeg(path, temporary_path)
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return len(paths)


def _dataset_image_count(root: Path) -> int:
    return sum(
        1
        for data_root in (root / "results", root / "ref_images")
        for path in _all_files(data_root)
        if path.suffix.casefold() in SUPPORTED_IMAGE_SUFFIXES
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and validate the generated evaluation dataset.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize_parser = subparsers.add_parser("normalize-tree")
    normalize_parser.add_argument("root", type=Path)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--root", required=True, type=Path)
    validate_parser.add_argument("--manifest", required=True, type=Path)
    validate_parser.add_argument("--prompt-root", type=Path)

    contact_parser = subparsers.add_parser("contact-sheet")
    contact_parser.add_argument("root", type=Path)
    contact_parser.add_argument("output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "normalize-tree":
        count = _normalize_tree(args.root)
        print(f"normalized {count} images")
        return 0
    if args.command == "validate":
        errors = validate_dataset(
            args.root,
            args.manifest,
            prompt_root=args.prompt_root,
        )
        print(f"validated {_dataset_image_count(args.root)} images; {len(errors)} errors")
        for error in errors:
            print(error)
        return 1 if errors else 0
    paths = [path for path in _discover_images(args.root) if path.resolve() != args.output.resolve()]
    render_contact_sheet(
        [(_relative(path, args.root), path) for path in paths],
        args.output,
    )
    print(f"rendered {len(paths)} images to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
