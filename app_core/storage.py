import io
import os
import shutil
import stat
import struct
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import config as app_config
from .config import IMAGE_EXTENSIONS, PROMPT_DIR, REF_IMAGE_DIR, RESULT_DIR, get_task_config, normalize_task_type
from .errors import AppError


def get_result_root(task_type: str) -> str:
    task_type = normalize_task_type(task_type)
    return get_task_config(task_type)["result_root"]


def get_result_roots(task_type: str) -> list[str]:
    task_type = normalize_task_type(task_type)
    preferred = get_result_root(task_type)
    if task_type == "T2I" and os.path.normpath(preferred) != os.path.normpath(RESULT_DIR):
        return [preferred, RESULT_DIR]
    return [preferred]


def get_prompt_root(task_type: str) -> str:
    config = get_task_config(normalize_task_type(task_type))
    preferred = config["prompt_root"]
    if os.path.isdir(preferred):
        return preferred
    return PROMPT_DIR


def get_ref_root(task_type: str) -> str:
    config = get_task_config(normalize_task_type(task_type))
    preferred = config["ref_root"]
    if os.path.isdir(preferred):
        return preferred
    return REF_IMAGE_DIR


def get_filesystem_model_names(task_type: str) -> List[str]:
    preferred = get_result_root(task_type)
    task_type_names = {normalize_task_type(name) for name in app_config.TASK_CONFIGS}
    task_roots = {
        os.path.normpath(str(config["result_root"]))
        for config in app_config.TASK_CONFIGS.values()
    }
    versions = set()
    for root in get_result_roots(task_type):
        if not os.path.isdir(root):
            continue
        versions.update(
            name
            for name in os.listdir(root)
            if os.path.isdir(os.path.join(root, name))
            and os.path.normpath(os.path.join(root, name)) != os.path.normpath(preferred)
            and os.path.normpath(os.path.join(root, name)) not in task_roots
            and normalize_task_type(name) not in task_type_names
        )
    return sorted(versions)


def get_versions_for_type(task_type: str) -> List[str]:
    return get_filesystem_model_names(task_type)


def get_scene_path(task_type: str, version: str, scene: str) -> str:
    for root in get_result_roots(task_type):
        scene_path = os.path.join(root, version, scene)
        if os.path.isdir(scene_path):
            return scene_path
    return os.path.join(get_result_root(task_type), version, scene)


def get_common_scenes(task_type: str, v1: str, v2: str) -> List[str]:
    def scenes_for_version(version: str) -> set[str]:
        scenes = set()
        for root in get_result_roots(task_type):
            version_path = os.path.join(root, version)
            if os.path.isdir(version_path):
                scenes.update(name for name in os.listdir(version_path) if os.path.isdir(os.path.join(version_path, name)))
        return scenes

    s1 = scenes_for_version(v1)
    s2 = scenes_for_version(v2)
    return sorted(list(s1 & s2))


def get_dataset_scenes(task_type: str) -> List[str]:
    prompt_root = get_prompt_root(task_type)
    candidates = [prompt_root]
    if prompt_root != PROMPT_DIR:
        candidates.append(PROMPT_DIR)

    scenes = set()
    for root in candidates:
        if not os.path.isdir(root):
            continue
        for filename in os.listdir(root):
            path = os.path.join(root, filename)
            if filename.lower().endswith(".txt") and os.path.isfile(path):
                scenes.add(os.path.splitext(filename)[0])
    return sorted(scenes)


def list_scene_files(task_type: str, version: str, scene: str) -> List[str]:
    scene_path = get_scene_path(task_type, version, scene)
    if not os.path.isdir(scene_path):
        return []
    return sorted([f for f in os.listdir(scene_path) if f.lower().endswith(IMAGE_EXTENSIONS)])


def get_image_dimensions(image_path: str) -> Optional[tuple[int, int]]:
    try:
        with open(image_path, "rb") as f:
            header = f.read(32)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                return struct.unpack(">II", header[16:24])
            if header[:2] == b"\xff\xd8":
                f.seek(2)
                return _read_jpeg_dimensions(f)
            if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
                return _read_webp_dimensions(header, f)
    except (OSError, struct.error):
        return None
    return None


def _read_jpeg_dimensions(f) -> Optional[tuple[int, int]]:
    while True:
        marker_start = f.read(1)
        if not marker_start:
            return None
        if marker_start != b"\xff":
            continue

        marker = f.read(1)
        while marker == b"\xff":
            marker = f.read(1)
        if not marker:
            return None

        marker_value = marker[0]
        if marker_value in (0xD8, 0xD9):
            continue
        if 0xD0 <= marker_value <= 0xD7:
            continue

        length_bytes = f.read(2)
        if len(length_bytes) != 2:
            return None
        segment_length = struct.unpack(">H", length_bytes)[0]
        if segment_length < 2:
            return None

        if marker_value in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            segment = f.read(segment_length - 2)
            if len(segment) >= 5:
                height, width = struct.unpack(">HH", segment[1:5])
                return width, height
            return None

        f.seek(segment_length - 2, os.SEEK_CUR)


def _read_webp_dimensions(header: bytes, f) -> Optional[tuple[int, int]]:
    chunk_type = header[12:16]
    if chunk_type == b"VP8X" and len(header) >= 30:
        width = int.from_bytes(header[24:27], "little") + 1
        height = int.from_bytes(header[27:30], "little") + 1
        return width, height
    if chunk_type == b"VP8 ":
        chunk = header + f.read(32)
        marker_index = chunk.find(b"\x9d\x01\x2a")
        if marker_index >= 0 and len(chunk) >= marker_index + 7:
            width = struct.unpack("<H", chunk[marker_index + 3 : marker_index + 5])[0] & 0x3FFF
            height = struct.unpack("<H", chunk[marker_index + 5 : marker_index + 7])[0] & 0x3FFF
            return width, height
    if chunk_type == b"VP8L" and len(header) >= 25 and header[20] == 0x2F:
        bits = int.from_bytes(header[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return None


def get_scene_resolution_stats(task_type: str, version: str, scene: str) -> dict:
    files = list_scene_files(task_type, version, scene)
    dimensions_by_file = {}
    unreadable = []

    for filename in files:
        image_path = os.path.join(get_scene_path(task_type, version, scene), filename)
        dimensions = get_image_dimensions(image_path)
        if dimensions:
            dimensions_by_file[filename] = {"width": dimensions[0], "height": dimensions[1]}
        else:
            unreadable.append(filename)

    widths = [item["width"] for item in dimensions_by_file.values()]
    heights = [item["height"] for item in dimensions_by_file.values()]
    unique_dimensions = sorted({(item["width"], item["height"]) for item in dimensions_by_file.values()})
    width_range = [min(widths), max(widths)] if widths else None
    height_range = [min(heights), max(heights)] if heights else None

    return {
        "version": version,
        "scene": scene,
        "total": len(files),
        "readable": len(dimensions_by_file),
        "unreadable": len(unreadable),
        "unreadable_files": unreadable[:20],
        "dimensions_by_file": dimensions_by_file,
        "unique_dimensions": [{"width": width, "height": height} for width, height in unique_dimensions],
        "width_range": width_range,
        "height_range": height_range,
        "range_label": format_resolution_range(width_range, height_range),
        "varied": len(unique_dimensions) > 1,
    }


def format_resolution_range(width_range: Optional[list[int]], height_range: Optional[list[int]]) -> str:
    if not width_range or not height_range:
        return "无法读取"
    width_label = str(width_range[0]) if width_range[0] == width_range[1] else f"{width_range[0]}-{width_range[1]}"
    height_label = str(height_range[0]) if height_range[0] == height_range[1] else f"{height_range[0]}-{height_range[1]}"
    return f"{width_label} x {height_label}"


def compare_scene_resolution_stats(task_type: str, v1: str, v2: str, scene: str) -> dict:
    stats_a = get_scene_resolution_stats(task_type, v1, scene)
    stats_b = get_scene_resolution_stats(task_type, v2, scene)
    files_a = set(stats_a["dimensions_by_file"])
    files_b = set(stats_b["dimensions_by_file"])
    common_files = sorted(files_a & files_b)
    mismatches = []

    for filename in common_files:
        dim_a = stats_a["dimensions_by_file"][filename]
        dim_b = stats_b["dimensions_by_file"][filename]
        if dim_a != dim_b:
            mismatches.append({"filename": filename, "a": dim_a, "b": dim_b})

    missing_a = sorted(set(list_scene_files(task_type, v2, scene)) - set(list_scene_files(task_type, v1, scene)))
    missing_b = sorted(set(list_scene_files(task_type, v1, scene)) - set(list_scene_files(task_type, v2, scene)))
    consistent = not mismatches and not missing_a and not missing_b and stats_a["unreadable"] == 0 and stats_b["unreadable"] == 0

    return {
        "task_type": normalize_task_type(task_type),
        "scene": scene,
        "models": {v1: compact_resolution_stats(stats_a), v2: compact_resolution_stats(stats_b)},
        "comparison": {
            "consistent": consistent,
            "common_count": len(common_files),
            "mismatch_count": len(mismatches),
            "mismatches": mismatches[:20],
            "missing_in_a": missing_a[:20],
            "missing_in_b": missing_b[:20],
            "missing_in_a_count": len(missing_a),
            "missing_in_b_count": len(missing_b),
        },
    }


def compact_resolution_stats(stats: dict) -> dict:
    return {
        "version": stats["version"],
        "scene": stats["scene"],
        "total": stats["total"],
        "readable": stats["readable"],
        "unreadable": stats["unreadable"],
        "unreadable_files": stats["unreadable_files"],
        "unique_dimensions": stats["unique_dimensions"],
        "width_range": stats["width_range"],
        "height_range": stats["height_range"],
        "range_label": stats["range_label"],
        "varied": stats["varied"],
    }


def get_prompt_text(task_type: str, scene: str, filename: str) -> str:
    prompt_root = get_prompt_root(task_type)
    candidates = [os.path.join(prompt_root, f"{scene}.txt"), os.path.join(PROMPT_DIR, f"{scene}.txt")]
    image_id = os.path.splitext(filename)[0]
    for prompt_file in candidates:
        if not os.path.exists(prompt_file):
            continue
        with open(prompt_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 2 and parts[0] == image_id:
                    return parts[1]
    return "Prompt content not found."


def get_prompt_file_path(task_type: str, scene: str) -> str:
    return os.path.join(get_prompt_root(task_type), f"{scene}.txt")


def parse_prompt_text(content: str) -> dict:
    ids = []
    prompts = {}
    errors = []

    for line_no, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            errors.append(f"第 {line_no} 行缺少 tab 分隔符")
            continue
        image_id, prompt = parts[0].strip(), parts[1].strip()
        if not image_id:
            errors.append(f"第 {line_no} 行图片名为空")
            continue
        if os.path.basename(image_id) != image_id or os.path.splitext(image_id)[1]:
            errors.append(f"第 {line_no} 行图片名应为不带路径和扩展名的前缀")
            continue
        if not prompt:
            errors.append(f"第 {line_no} 行 prompt 为空")
            continue
        if image_id in prompts:
            errors.append(f"第 {line_no} 行图片名重复: {image_id}")
            continue
        ids.append(image_id)
        prompts[image_id] = prompt

    if not ids:
        errors.append("prompt 文件没有有效内容")
    if errors:
        raise AppError("Prompt 格式检查失败：" + "；".join(errors[:8]))
    return {"ids": ids, "prompts": prompts, "count": len(ids)}


def parse_prompt_file_bytes(file_bytes: bytes) -> dict:
    try:
        content = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError("Prompt 文件必须是 UTF-8 文本") from exc
    return parse_prompt_text(content)


def get_prompt_ids(task_type: str, scene: str) -> list[str]:
    prompt_file = get_prompt_file_path(task_type, scene)
    fallback = os.path.join(PROMPT_DIR, f"{scene}.txt")
    for path in (prompt_file, fallback):
        if os.path.exists(path):
            with open(path, "rb") as f:
                return parse_prompt_file_bytes(f.read())["ids"]
    raise AppError(f"未找到场景 {scene} 的 prompt 文件")


def save_prompt_file(task_type: str, scene: str, file_bytes: bytes):
    parse_prompt_file_bytes(file_bytes)
    scene = validate_storage_component(scene, "场景")
    prompt_root = get_task_config(normalize_task_type(task_type))["prompt_root"]
    os.makedirs(prompt_root, exist_ok=True)
    with open(os.path.join(prompt_root, f"{scene}.txt"), "wb") as f:
        f.write(file_bytes)


def upload_dataset(task_type: str, scene: str, prompt_file, ref_file=None) -> dict:
    task_type = normalize_task_type(task_type)
    scene = validate_storage_component(scene, "场景")
    prompt_bytes = read_upload_bytes(prompt_file)
    prompt_info = parse_prompt_file_bytes(prompt_bytes)

    if task_type == "TI2I":
        if not ref_file:
            raise AppError("TI2I 测评集需要上传参考图 zip")
        ref_bytes = read_upload_bytes(ref_file)
        validate_image_zip_against_ids(ref_bytes, prompt_info["ids"], "参考图")
        ref_root = get_task_config(task_type)["ref_root"]
        save_zip_images(os.path.join(ref_root, scene), ref_bytes)

    save_prompt_file(task_type, scene, prompt_bytes)
    return {"message": "Success", "scene": scene, "prompt_count": prompt_info["count"]}


def get_ref_image_url(task_type: str, scene: str, filename: str) -> Optional[str]:
    ref_root = get_ref_root(task_type)
    direct_path = os.path.join(ref_root, scene, filename)
    if os.path.exists(direct_path):
        rel = os.path.relpath(direct_path, REF_IMAGE_DIR).replace(os.sep, "/")
        return f"/ref-images/{rel}"

    fallback = os.path.join(REF_IMAGE_DIR, scene, filename)
    if os.path.exists(fallback):
        rel = os.path.relpath(fallback, REF_IMAGE_DIR).replace(os.sep, "/")
        return f"/ref-images/{rel}"
    return None


def get_result_image_url(task_type: str, version: str, scene: str, filename: str) -> str:
    for root in get_result_roots(task_type):
        image_path = os.path.join(root, version, scene, filename)
        if os.path.isfile(image_path):
            rel = os.path.relpath(image_path, RESULT_DIR).replace(os.sep, "/")
            return f"/images/{rel}"
    rel = os.path.relpath(os.path.join(get_scene_path(task_type, version, scene), filename), RESULT_DIR).replace(os.sep, "/")
    return f"/images/{rel}"


def _safe_existing_file_path(root: str, *components: str) -> Optional[str]:
    root_path = Path(root)
    candidate = root_path.joinpath(*components)
    try:
        current = root_path
        if current.is_symlink():
            return None
        for component in components:
            current = current / component
            if current.is_symlink():
                return None

        resolved_root = root_path.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
        if not resolved_candidate.is_file():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return os.fspath(candidate)


def get_regular_file_identity(source_path: str) -> Optional[tuple[int, int, int, int]]:
    try:
        source_stat = os.stat(source_path, follow_symlinks=False)
    except (OSError, ValueError):
        return None
    if not stat.S_ISREG(source_stat.st_mode):
        return None
    return (source_stat.st_dev, source_stat.st_ino, source_stat.st_size, source_stat.st_mtime_ns)


def copy_regular_file_without_symlinks(
    source_path: str,
    destination_path: str,
    expected_identity: Optional[tuple[int, int, int, int]] = None,
) -> bool:
    absolute_source = os.path.abspath(source_path)
    if not os.path.isabs(absolute_source) or not hasattr(os, "O_NOFOLLOW"):
        return False

    source_identity = expected_identity or get_regular_file_identity(absolute_source)
    if source_identity is None:
        return False

    # Resolve the parent only. The final component must still be opened with
    # O_NOFOLLOW, while the stored identity detects parent-directory swaps.
    canonical_parent = os.path.realpath(os.path.dirname(absolute_source))
    parts = Path(canonical_parent).parts
    if len(parts) < 1:
        return False

    directory_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    opened_directories = []
    file_descriptor = None
    try:
        current_directory = os.open(parts[0], directory_flags)
        opened_directories.append(current_directory)
        for component in parts[1:]:
            current_directory = os.open(component, directory_flags, dir_fd=current_directory)
            opened_directories.append(current_directory)
        file_descriptor = os.open(os.path.basename(absolute_source), file_flags, dir_fd=current_directory)
        opened_stat = os.fstat(file_descriptor)
        opened_identity = (
            opened_stat.st_dev,
            opened_stat.st_ino,
            opened_stat.st_size,
            opened_stat.st_mtime_ns,
        )
        if not stat.S_ISREG(opened_stat.st_mode) or opened_identity != tuple(source_identity):
            return False
        with os.fdopen(file_descriptor, "rb") as source, open(destination_path, "xb") as destination:
            file_descriptor = None
            shutil.copyfileobj(source, destination)
        return True
    except (OSError, RuntimeError, ValueError):
        try:
            os.remove(destination_path)
        except OSError:
            pass
        return False
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for directory_descriptor in reversed(opened_directories):
            os.close(directory_descriptor)


def get_result_image_path(task_type: str, version: str, scene: str, filename: str) -> Optional[str]:
    task_type = validate_storage_component(normalize_task_type(task_type), "任务类型")
    version = validate_storage_component(version, "模型")
    scene = validate_storage_component(scene, "场景")
    filename = validate_storage_component(filename, "图片名")
    for root in get_result_roots(task_type):
        path = _safe_existing_file_path(root, version, scene, filename)
        if path:
            return path
    return None


def get_ref_image_path(task_type: str, scene: str, filename: str) -> Optional[str]:
    task_type = validate_storage_component(normalize_task_type(task_type), "任务类型")
    scene = validate_storage_component(scene, "场景")
    filename = validate_storage_component(filename, "图片名")
    roots = [get_ref_root(task_type), REF_IMAGE_DIR]
    for root in roots:
        path = _safe_existing_file_path(root, scene, filename)
        if path:
            return path
    return None


def validate_storage_component(value: str, label: str) -> str:
    component = value.strip() if isinstance(value, str) else ""
    if (
        not component
        or component in {".", ".."}
        or os.path.isabs(component)
        or "/" in component
        or "\\" in component
        or os.path.basename(component) != component
    ):
        raise AppError(f"{label}必须是有效的目录名")
    return component


def read_upload_bytes(upload_file) -> bytes:
    upload_file.file.seek(0)
    data = upload_file.file.read()
    upload_file.file.seek(0)
    if not data:
        raise AppError("上传文件为空")
    return data


def clean_zip_basename(name: str) -> str:
    return name.replace("\\", "/").split("/")[-1]


def zip_image_infos(zip_bytes: bytes) -> list[dict]:
    infos = []
    seen_basenames = set()
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                basename = clean_zip_basename(info.filename)
                if not basename or basename.startswith(".") or "__MACOSX" in info.filename:
                    continue
                stem, ext = os.path.splitext(basename)
                if ext.lower() not in IMAGE_EXTENSIONS:
                    continue
                if basename in seen_basenames:
                    raise AppError(f"zip 中存在重复图片文件名: {basename}")
                seen_basenames.add(basename)
                infos.append({"entry": info.filename, "basename": basename, "stem": stem, "ext": ext.lower()})
    except zipfile.BadZipFile as exc:
        raise AppError("上传文件不是有效 zip") from exc
    if not infos:
        raise AppError("zip 中没有可用图片文件")
    return infos


def build_exact_name_map(image_infos: list[dict], expected_ids: list[str]) -> Optional[dict]:
    stems = {item["stem"] for item in image_infos}
    expected = set(expected_ids)
    if len(stems) == len(image_infos) and stems == expected:
        return {item["entry"]: item["basename"] for item in image_infos}
    return None


def build_prefix_name_map(image_infos: list[dict], expected_ids: list[str]) -> Optional[dict]:
    expected = set(expected_ids)
    assignments = {}
    used_entries = set()
    sorted_ids = sorted(expected_ids, key=len, reverse=True)

    for item in image_infos:
        matches = [image_id for image_id in sorted_ids if item["stem"].startswith(image_id)]
        if not matches:
            return None
        image_id = matches[0]
        if image_id in assignments:
            return None
        assignments[image_id] = item
        used_entries.add(item["entry"])

    if set(assignments) != expected or len(used_entries) != len(image_infos):
        return None
    return {item["entry"]: f"{image_id}{item['ext']}" for image_id, item in assignments.items()}


def image_name_diff(image_infos: list[dict], expected_ids: list[str]) -> dict:
    stems = {item["stem"] for item in image_infos}
    expected = set(expected_ids)
    return {
        "missing": sorted(expected - stems)[:20],
        "extra": sorted(stems - expected)[:20],
        "missing_count": len(expected - stems),
        "extra_count": len(stems - expected),
    }


def validate_image_zip_against_ids(zip_bytes: bytes, expected_ids: list[str], label: str) -> dict:
    infos = zip_image_infos(zip_bytes)
    exact_map = build_exact_name_map(infos, expected_ids)
    if exact_map:
        return {"status": "exact", "rename_map": exact_map}
    diff = image_name_diff(infos, expected_ids)
    raise AppError(
        f"{label} 图片名和 prompt 不匹配：缺少 {diff['missing_count']} 个，多出 {diff['extra_count']} 个"
        + (f"；缺少示例: {', '.join(diff['missing'])}" if diff["missing"] else "")
        + (f"；多出示例: {', '.join(diff['extra'])}" if diff["extra"] else "")
    )


def validate_result_zip(task_type: str, scene: str, zip_bytes: bytes, auto_rename: bool = False) -> dict:
    expected_ids = get_prompt_ids(task_type, scene)
    infos = zip_image_infos(zip_bytes)
    exact_map = build_exact_name_map(infos, expected_ids)
    if exact_map:
        return {"status": "exact", "rename_map": exact_map, "image_count": len(infos)}

    prefix_map = build_prefix_name_map(infos, expected_ids)
    if prefix_map:
        if not auto_rename:
            examples = [f"{clean_zip_basename(src)} -> {dst}" for src, dst in list(prefix_map.items())[:5]]
            return {
                "status": "requires_rename_confirmation",
                "message": "当前图片名称前缀匹配 prompt 文件中的图片名，可以自动格式化名称后上传。是否继续？"
                + (f"\n示例：{'; '.join(examples)}" if examples else ""),
                "image_count": len(infos),
            }
        return {"status": "renamed", "rename_map": prefix_map, "image_count": len(infos)}

    diff = image_name_diff(infos, expected_ids)
    raise AppError(
        f"结果图图片名和 prompt 不匹配：缺少 {diff['missing_count']} 个，多出 {diff['extra_count']} 个"
        + (f"；缺少示例: {', '.join(diff['missing'])}" if diff["missing"] else "")
        + (f"；多出示例: {', '.join(diff['extra'])}" if diff["extra"] else "")
    )


def upload_ref_zip(task_type: str, scene: str, upload_file) -> dict:
    task_type = normalize_task_type(task_type)
    scene = validate_storage_component(scene, "场景")
    zip_bytes = read_upload_bytes(upload_file)
    validation = validate_image_zip_against_ids(zip_bytes, get_prompt_ids(task_type, scene), "参考图")
    save_zip_images(os.path.join(get_ref_root(task_type), scene), zip_bytes, validation.get("rename_map"))
    return {"message": "Success"}


def save_zip_images(target_path: str, zip_bytes: bytes, rename_map: Optional[dict] = None):
    if os.path.exists(target_path):
        shutil.rmtree(target_path)
    os.makedirs(target_path, exist_ok=True)

    rename_map = rename_map or {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            basename = clean_zip_basename(info.filename)
            if not basename or basename.startswith(".") or "__MACOSX" in info.filename:
                continue
            stem, ext = os.path.splitext(basename)
            if ext.lower() not in IMAGE_EXTENSIONS:
                continue
            output_name = rename_map.get(info.filename, basename)
            with zf.open(info, "r") as src, open(os.path.join(target_path, output_name), "wb") as dst:
                shutil.copyfileobj(src, dst)


def upload_result_zip(
    task_type: str,
    class_name: str,
    model_name: str,
    version: str,
    scene: str,
    upload_file,
    auto_rename: bool = False,
) -> dict:
    from .model_catalog import compose_model_name

    task_type = normalize_task_type(task_type)
    full_name = compose_model_name(class_name, model_name, version)
    scene = validate_storage_component(scene, "场景")
    zip_bytes = read_upload_bytes(upload_file)
    validation = validate_result_zip(task_type, scene, zip_bytes, auto_rename=auto_rename)
    if validation["status"] == "requires_rename_confirmation":
        return validation
    result_root = get_task_config(task_type)["result_root"]
    save_zip_images(os.path.join(result_root, full_name, scene), zip_bytes, validation.get("rename_map"))
    return {
        "message": "Success",
        "status": validation["status"],
        "image_count": validation["image_count"],
        "full_name": full_name,
    }


def save_uploaded_zip(target_path: str, upload_file):
    if os.path.exists(target_path):
        shutil.rmtree(target_path)
    os.makedirs(target_path, exist_ok=True)

    temp_zip = f"temp_{datetime.utcnow().timestamp():.0f}_{upload_file.filename}"
    with open(temp_zip, "wb") as f:
        shutil.copyfileobj(upload_file.file, f)

    try:
        with zipfile.ZipFile(temp_zip, "r") as zf:
            zf.extractall(target_path)
        items = [item for item in os.listdir(target_path) if not item.startswith(".") and item != "__MACOSX"]
        if len(items) == 1 and os.path.isdir(os.path.join(target_path, items[0])):
            inner = os.path.join(target_path, items[0])
            for name in os.listdir(inner):
                shutil.move(os.path.join(inner, name), target_path)
            os.rmdir(inner)
    finally:
        if os.path.exists(temp_zip):
            os.remove(temp_zip)
