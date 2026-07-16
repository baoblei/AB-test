from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps


Box = tuple[int, int, int, int]


def _rgb(image: Image.Image) -> Image.Image:
    return image.convert("RGB")


def _box_size(box: Box) -> tuple[int, int]:
    return box[2] - box[0], box[3] - box[1]


def _feather_paste(
    image: Image.Image,
    patch: Image.Image,
    xy: tuple[int, int],
    radius: float = 10,
) -> None:
    mask = Image.new("L", patch.size, 0)
    margin = max(1, round(radius))
    mask.paste(
        255,
        (
            min(margin, patch.width // 3),
            min(margin, patch.height // 3),
            max(patch.width - margin, patch.width * 2 // 3),
            max(patch.height - margin, patch.height * 2 // 3),
        ),
    )
    mask = mask.filter(ImageFilter.GaussianBlur(radius=radius))
    image.paste(patch, xy, mask)


def clone_region(image: Image.Image, source: Box, target: Box) -> Image.Image:
    result = _rgb(image).copy()
    patch = result.crop(source).resize(_box_size(target), Image.Resampling.LANCZOS)
    result.paste(patch, target)
    return result


def tint_region(
    image: Image.Image,
    box: Box,
    color: tuple[int, int, int],
    strength: float,
) -> Image.Image:
    if not 0 <= strength <= 1:
        raise ValueError("strength must be between 0 and 1")
    result = _rgb(image).copy()
    patch = result.crop(box)
    overlay = Image.new("RGB", patch.size, color)
    result.paste(Image.blend(patch, overlay, strength), box)
    return result


def warp_region(
    image: Image.Image,
    box: Box,
    *,
    x_scale: float,
    y_shift: int = 0,
) -> Image.Image:
    if not 0.2 <= x_scale <= 1.8:
        raise ValueError("x_scale must be between 0.2 and 1.8")
    result = _rgb(image).copy()
    width, height = _box_size(box)
    patch = result.crop(box)
    warped_width = max(1, round(width * x_scale))
    warped = patch.resize((warped_width, height), Image.Resampling.BICUBIC)

    expanded = (
        max(0, box[0] - 8),
        max(0, box[1] - 8),
        min(result.width, box[2] + 8),
        min(result.height, box[3] + 8),
    )
    fill = result.crop(expanded).resize((width, height), Image.Resampling.BILINEAR)
    fill = fill.filter(ImageFilter.GaussianBlur(radius=5))
    result.paste(fill, box)

    x = box[0] + (width - warped_width) // 2
    y = max(box[1], min(box[3] - height, box[1] + y_shift))
    mask = Image.new("L", warped.size, 255).filter(ImageFilter.GaussianBlur(radius=1.2))
    result.paste(warped, (x, y), mask)
    return result


def move_region(
    image: Image.Image,
    source: Box,
    target: Box,
    fill_source: Box,
) -> Image.Image:
    result = _rgb(image).copy()
    patch = result.crop(source).resize(_box_size(target), Image.Resampling.LANCZOS)
    fill = result.crop(fill_source).resize(_box_size(source), Image.Resampling.BILINEAR)
    fill = fill.filter(ImageFilter.GaussianBlur(radius=2))
    result.paste(fill, source)
    result.paste(patch, target)
    return result


def save_jpeg_contract(image: Image.Image, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized = ImageOps.fit(
        _rgb(image),
        (768, 768),
        method=Image.Resampling.LANCZOS,
    )
    temporary = destination.with_suffix(".tmp.jpg")
    normalized.save(temporary, "JPEG", quality=85, optimize=True, exif=b"")
    os.replace(temporary, destination)


def _open_normalized(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return ImageOps.fit(
            image.convert("RGB"),
            (768, 768),
            method=Image.Resampling.LANCZOS,
        )


def _write(
    fix_root: Path,
    relative_path: str,
    image: Image.Image,
    records: list[dict],
    rule: str,
) -> None:
    destination = fix_root / relative_path
    save_jpeg_contract(image, destination)
    records.append({"path": relative_path, "rule": rule})


def build_review_fix_wave(root: Path, fix_root: Path) -> list[dict]:
    records: list[dict] = []

    portrait_base = _open_normalized(
        fix_root / "bases/lane1/portrait_05-high-base.png"
    )
    portrait_paths = {
        "Atlas": "results/T2I/Atlas/portrait_anatomy/portrait_05.jpg",
        "Beacon": "results/T2I/Beacon/portrait_anatomy/portrait_05.jpg",
        "Cipher": "results/T2I/Cipher/portrait_anatomy/portrait_05.jpg",
    }
    _write(fix_root, portrait_paths["Atlas"], portrait_base, records, "new compliant base")
    portrait_medium = clone_region(
        portrait_base, (480, 420, 505, 452), (463, 434, 488, 472)
    )
    _write(
        fix_root,
        portrait_paths["Beacon"],
        portrait_medium,
        records,
        "small soil patch obscures one seedling-hand finger",
    )
    portrait_weak = clone_region(
        portrait_base, (478, 416, 510, 458), (450, 421, 494, 486)
    )
    _write(
        fix_root,
        portrait_paths["Cipher"],
        portrait_weak,
        records,
        "large soil patch obscures several seedling-hand fingers",
    )

    spatial_base = _open_normalized(fix_root / "bases/lane1/spatial_03-high-base.png")
    spatial_paths = {
        "Atlas": "results/T2I/Atlas/spatial_composition/spatial_03.jpg",
        "Beacon": "results/T2I/Beacon/spatial_composition/spatial_03.jpg",
        "Cipher": "results/T2I/Cipher/spatial_composition/spatial_03.jpg",
    }
    _write(fix_root, spatial_paths["Atlas"], spatial_base, records, "new compliant base")
    spatial_medium = _open_normalized(
        root / "results/T2I/Beacon/spatial_composition/spatial_03.jpg"
    )
    _write(
        fix_root,
        spatial_paths["Beacon"],
        spatial_medium,
        records,
        "mailbox moved left of bench",
    )
    spatial_weak_source = _open_normalized(
        root / "results/T2I/Cipher/spatial_composition/spatial_03.jpg"
    )
    spatial_weak = warp_region(
        spatial_weak_source, (28, 372, 148, 616), x_scale=0.58, y_shift=7
    )
    _write(
        fix_root,
        spatial_paths["Cipher"],
        spatial_weak,
        records,
        "mailbox moved left and strongly distorted",
    )

    spatial_04_medium = _open_normalized(
        root / "results/T2I/Beacon/spatial_composition/spatial_04.jpg"
    )
    spatial_04_weak = clone_region(
        spatial_04_medium, (156, 112, 214, 360), (382, 112, 440, 360)
    )
    _write(
        fix_root,
        "results/T2I/Cipher/spatial_composition/spatial_04.jpg",
        spatial_04_weak,
        records,
        "second extra book duplicated beside clock",
    )

    spatial_05_medium = _open_normalized(
        root / "results/T2I/Beacon/spatial_composition/spatial_05.jpg"
    )
    spatial_05_weak = clone_region(
        spatial_05_medium, (610, 110, 765, 310), (590, 300, 768, 585)
    )
    _write(
        fix_root,
        "results/T2I/Cipher/spatial_composition/spatial_05.jpg",
        spatial_05_weak,
        records,
        "right table area removed with severe reconstruction",
    )

    spatial_06_source = _open_normalized(
        root / "results/T2I/Atlas/spatial_composition/spatial_06.jpg"
    )
    _write(
        fix_root,
        "results/T2I/Atlas/spatial_composition/spatial_06.jpg",
        spatial_06_source,
        records,
        "clean four-stool medium",
    )
    spatial_06_beacon = warp_region(
        spatial_06_source, (205, 425, 390, 760), x_scale=0.82, y_shift=1
    )
    _write(
        fix_root,
        "results/T2I/Beacon/spatial_composition/spatial_06.jpg",
        spatial_06_beacon,
        records,
        "four stools with one warped stool",
    )
    spatial_06_cipher = warp_region(
        spatial_06_source, (205, 425, 390, 760), x_scale=0.56, y_shift=8
    )
    spatial_06_cipher = warp_region(
        spatial_06_cipher, (390, 425, 575, 760), x_scale=0.52, y_shift=-5
    )
    _write(
        fix_root,
        "results/T2I/Cipher/spatial_composition/spatial_06.jpg",
        spatial_06_cipher,
        records,
        "four stools with two strongly warped stools",
    )

    text_warps = {
        "text_03": ((225, 145, 548, 210), 0.72, 8),
        "text_04": ((270, 400, 525, 570), 0.68, 11),
        "text_05": ((278, 370, 492, 462), 0.60, 9),
    }
    for sample_id, (box, scale, shift) in text_warps.items():
        source = _open_normalized(
            root / f"results/T2I/Cipher/text_product/{sample_id}.jpg"
        )
        weak = warp_region(source, box, x_scale=scale, y_shift=shift)
        _write(
            fix_root,
            f"results/T2I/Cipher/text_product/{sample_id}.jpg",
            weak,
            records,
            f"strong local typography warp for {sample_id}",
        )

    text_06_source = _open_normalized(
        root / "results/T2I/Atlas/text_product/text_06.jpg"
    )
    _write(
        fix_root,
        "results/T2I/Atlas/text_product/text_06.jpg",
        text_06_source,
        records,
        "crisp 2AH medium",
    )
    text_06_beacon = warp_region(
        text_06_source, (145, 365, 515, 525), x_scale=0.86, y_shift=4
    )
    _write(
        fix_root,
        "results/T2I/Beacon/text_product/text_06.jpg",
        text_06_beacon,
        records,
        "2AH with uneven compact typography",
    )
    text_06_cipher = warp_region(
        text_06_source, (130, 350, 530, 535), x_scale=0.58, y_shift=13
    )
    _write(
        fix_root,
        "results/T2I/Cipher/text_product/text_06.jpg",
        text_06_cipher,
        records,
        "2AH with severe typography compression",
    )

    object_02_source = _open_normalized(
        root / "results/TI2I/Prism/object_edit/object_edit_02.jpg"
    )
    object_02_changed = tint_region(
        object_02_source, (126, 275, 158, 490), (176, 38, 34), 0.78
    )
    _write(
        fix_root,
        "results/TI2I/Prism/object_edit/object_edit_02.jpg",
        object_02_changed,
        records,
        "one shelf book changed to red",
    )

    if len(records) != 18:
        raise RuntimeError(f"expected 18 replacements, built {len(records)}")
    (fix_root / "rule-perturbations.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return records


def install_fix_wave(root: Path, fix_root: Path, records: list[dict]) -> None:
    for record in records:
        source = fix_root / record["path"]
        destination = root / record["path"]
        if not source.is_file():
            raise FileNotFoundError(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("fix_root", type=Path)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    records = build_review_fix_wave(args.root, args.fix_root)
    if args.install:
        install_fix_wave(args.root, args.fix_root, records)
    print(f"built {len(records)} deterministic replacements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
