#!/usr/bin/env python3
"""Generate deterministic mock T2V/TI2V evaluation assets."""

import argparse
import json
import math
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIZE = (640, 360)
FPS = 12
FRAME_COUNT = 48
T2V_MODELS = ("test_Nova_default", "test_Orbit_default")
TI2V_MODELS = ("test_Frame_default", "test_Flow_default")

T2V_PROMPTS = (
    ("motion_01", "A coral sphere rolls smoothly from left to right on a navy track."),
    ("motion_02", "A cyan satellite follows a clean circular orbit around a glowing center."),
    ("motion_03", "Three golden blocks bounce in sequence while keeping their shape."),
)
TI2V_PROMPTS = (
    ("animation_01", "Animate the coral circle gliding across the scene while preserving its appearance."),
    ("animation_02", "Animate the cyan diamond orbiting the central light without changing the image style."),
    ("animation_03", "Animate the three golden bars bouncing rhythmically with consistent colors and details."),
)

BACKGROUND = (13, 22, 39)
PANEL = (21, 35, 58)
GRID = (34, 52, 78)
TEXT = (232, 240, 250)
MUTED = (142, 161, 188)
CORAL = (250, 112, 112)
CYAN = (66, 211, 228)
GOLD = (250, 198, 74)


def expected_paths():
    videos = []
    for model in T2V_MODELS:
        videos.extend(
            PROJECT_ROOT / "results" / "T2V" / model / "motion_basics" / f"{item_id}.mp4"
            for item_id, _prompt in T2V_PROMPTS
        )
    for model in TI2V_MODELS:
        videos.extend(
            PROJECT_ROOT / "results" / "TI2V" / model / "image_animation" / f"{item_id}.mp4"
            for item_id, _prompt in TI2V_PROMPTS
        )
    references = [
        PROJECT_ROOT / "ref_images" / "TI2V" / "image_animation" / f"{item_id}.png"
        for item_id, _prompt in TI2V_PROMPTS
    ]
    prompts = [
        PROJECT_ROOT / "prompt" / "T2V" / "motion_basics.txt",
        PROJECT_ROOT / "prompt" / "TI2V" / "image_animation.txt",
    ]
    return videos, references, prompts


def write_prompt(path: Path, prompts) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{item_id}\t{prompt}\n" for item_id, prompt in prompts)
    path.write_text(content, encoding="utf-8")


def ease_progress(model: str, frame_index: int) -> float:
    progress = frame_index / (FRAME_COUNT - 1)
    if model in {"test_Orbit_default", "test_Flow_default"}:
        return 0.5 - 0.5 * math.cos(math.pi * progress)
    return progress


def draw_background(draw: ImageDraw.ImageDraw, item_id: str, model_label: str) -> None:
    draw.rectangle((0, 0, SIZE[0], SIZE[1]), fill=BACKGROUND)
    for x in range(0, SIZE[0], 40):
        draw.line((x, 70, x, SIZE[1]), fill=GRID, width=1)
    for y in range(80, SIZE[1], 40):
        draw.line((0, y, SIZE[0], y), fill=GRID, width=1)
    draw.rounded_rectangle((18, 16, 622, 62), radius=14, fill=PANEL)
    draw.text((36, 29), item_id.upper(), fill=TEXT)
    label_width = draw.textbbox((0, 0), model_label)[2]
    draw.text((602 - label_width, 29), model_label, fill=MUTED)


def draw_scene(
    item_index: int,
    item_id: str,
    model: str,
    frame_index: int,
    reference: bool = False,
) -> Image.Image:
    image = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    model_label = "TI2V REFERENCE" if reference else model.replace("test_", "").replace("_default", "")
    draw_background(draw, item_id, model_label)
    progress = 0.0 if reference else ease_progress(model, frame_index)
    alternate = model in {"test_Orbit_default", "test_Flow_default"}

    if item_index == 0:
        draw.rounded_rectangle((78, 270, 562, 288), radius=9, fill=(64, 82, 108))
        x = 105 + int(420 * progress)
        y = 238 - (int(30 * math.sin(progress * math.pi * 4)) if alternate else 0)
        radius = 37
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=CORAL)
        marker_angle = progress * math.pi * (8 if alternate else 5)
        marker = (x + int(25 * math.cos(marker_angle)), y + int(25 * math.sin(marker_angle)))
        draw.line((x, y, marker[0], marker[1]), fill=(116, 35, 50), width=5)
        draw.text((82, 306), "ROLL / GLIDE", fill=MUTED)
    elif item_index == 1:
        center = (320, 205)
        orbit_radius = 118
        draw.ellipse(
            (
                center[0] - orbit_radius,
                center[1] - orbit_radius,
                center[0] + orbit_radius,
                center[1] + orbit_radius,
            ),
            outline=(72, 104, 137),
            width=3,
        )
        draw.ellipse((294, 179, 346, 231), fill=(248, 231, 151))
        angle = -math.pi / 2 + progress * math.pi * (4 if alternate else 2)
        x = center[0] + int(orbit_radius * math.cos(angle))
        y = center[1] + int(orbit_radius * math.sin(angle))
        points = [(x, y - 28), (x + 28, y), (x, y + 28), (x - 28, y)]
        draw.polygon(points, fill=CYAN)
        draw.line((center[0], center[1], x, y), fill=(50, 81, 111), width=2)
        draw.text((82, 306), "ORBIT / ROTATION", fill=MUTED)
    else:
        base_y = 282
        for index, x in enumerate((205, 300, 395)):
            phase = progress * math.pi * (8 if alternate else 6) - index * 0.8
            lift = max(0.0, math.sin(phase)) * (86 if alternate else 66)
            height = 58 + index * 8
            draw.rounded_rectangle(
                (x, int(base_y - height - lift), x + 48, int(base_y - lift)),
                radius=9,
                fill=GOLD,
            )
        draw.line((150, base_y + 2, 490, base_y + 2), fill=(84, 98, 120), width=4)
        draw.text((82, 306), "SEQUENTIAL BOUNCE", fill=MUTED)

    draw.rounded_rectangle((492, 310, 606, 338), radius=10, outline=(65, 88, 117), width=2)
    draw.text((512, 319), "MOCK 4s", fill=MUTED)
    return image


def write_video(output_path: Path, task_type: str, model: str, item_index: int, item_id: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio_ffmpeg.write_frames(
        str(output_path),
        SIZE,
        fps=FPS,
        codec="libx264",
        pix_fmt_in="rgb24",
        pix_fmt_out="yuv420p",
        macro_block_size=1,
        output_params=[
            "-movflags",
            "+faststart",
            "-an",
            "-metadata",
            f"comment=deterministic-{task_type.lower()}-mock",
        ],
    )
    writer.send(None)
    try:
        for frame_index in range(FRAME_COUNT):
            frame = draw_scene(item_index, item_id, model, frame_index)
            writer.send(frame.tobytes())
    finally:
        writer.close()


def generate() -> dict:
    write_prompt(PROJECT_ROOT / "prompt" / "T2V" / "motion_basics.txt", T2V_PROMPTS)
    write_prompt(PROJECT_ROOT / "prompt" / "TI2V" / "image_animation.txt", TI2V_PROMPTS)

    generated_videos = 0
    for task_type, models, scene, prompts in (
        ("T2V", T2V_MODELS, "motion_basics", T2V_PROMPTS),
        ("TI2V", TI2V_MODELS, "image_animation", TI2V_PROMPTS),
    ):
        for model in models:
            for item_index, (item_id, _prompt) in enumerate(prompts):
                output_path = PROJECT_ROOT / "results" / task_type / model / scene / f"{item_id}.mp4"
                write_video(output_path, task_type, model, item_index, item_id)
                generated_videos += 1

    reference_root = PROJECT_ROOT / "ref_images" / "TI2V" / "image_animation"
    reference_root.mkdir(parents=True, exist_ok=True)
    for item_index, (item_id, _prompt) in enumerate(TI2V_PROMPTS):
        draw_scene(item_index, item_id, TI2V_MODELS[0], 0, reference=True).save(
            reference_root / f"{item_id}.png",
            format="PNG",
            optimize=True,
        )
    return {"videos": generated_videos, "references": len(TI2V_PROMPTS), "missing": []}


def check() -> dict:
    videos, references, prompts = expected_paths()
    missing = [
        str(path.relative_to(PROJECT_ROOT))
        for path in [*videos, *references, *prompts]
        if not path.is_file() or path.stat().st_size == 0
    ]
    return {"videos": len(videos), "references": len(references), "missing": missing}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only verify that every generated asset exists")
    args = parser.parse_args()
    report = check() if args.check else generate()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["missing"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
