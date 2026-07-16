from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .config import IMAGE_EXTENSIONS, normalize_task_type
from .errors import AppError
from .storage import (
    get_dataset_scenes,
    get_prompt_file_path,
    get_ref_root,
    parse_prompt_file_bytes,
    validate_storage_component,
)

TXT_MEDIA_TYPE = "text/plain; charset=utf-8"
ZIP_MEDIA_TYPE = "application/zip"


@dataclass(frozen=True)
class DatasetArtifact:
    path: str
    filename: str
    media_type: str
    cleanup_dir: str | None = None


def _prompt_path(task_type: str, scene: str) -> Path:
    task_type = normalize_task_type(task_type)
    scene = validate_storage_component(scene, "场景")
    path = Path(get_prompt_file_path(task_type, scene))
    if not path.is_file():
        raise AppError(f"未找到场景 {scene} 的 prompt 文件")
    return path


def list_datasets(task_type: str) -> list[dict]:
    task_type = normalize_task_type(task_type)
    datasets = []
    for scene in get_dataset_scenes(task_type):
        parsed = parse_prompt_file_bytes(_prompt_path(task_type, scene).read_bytes())
        datasets.append({"scene": scene, "prompt_count": parsed["count"]})
    return datasets


def _reference_files(task_type: str, scene: str, prompt_ids: list[str]) -> list[Path]:
    scene_root = Path(get_ref_root(task_type)) / scene
    if not scene_root.is_dir() or scene_root.is_symlink():
        raise AppError(f"未找到场景 {scene} 的参考图")
    files = [
        path for path in scene_root.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise AppError("参考图目录包含不安全文件")
    stems = [path.stem for path in files]
    if len(stems) != len(set(stems)):
        raise AppError("参考图存在重复图片 ID")
    missing = sorted(set(prompt_ids) - set(stems))
    extra = sorted(set(stems) - set(prompt_ids))
    if missing or extra:
        raise AppError(
            f"参考图和 prompt 不匹配：缺少 {len(missing)} 个，多出 {len(extra)} 个"
        )
    return sorted(files, key=lambda path: path.name)


def _create_ti2i_archive(
    scene: str, prompt_path: Path, ref_files: list[Path]
) -> DatasetArtifact:
    cleanup_dir = tempfile.mkdtemp(prefix="ab-test-dataset-")
    archive_path = Path(cleanup_dir) / f"{scene}.zip"
    try:
        with zipfile.ZipFile(
            archive_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.write(prompt_path, f"{scene}.txt")
            for ref_path in ref_files:
                archive.write(ref_path, f"ref_images/{ref_path.name}")
        return DatasetArtifact(
            str(archive_path), f"{scene}.zip", ZIP_MEDIA_TYPE, cleanup_dir
        )
    except Exception:
        shutil.rmtree(cleanup_dir, ignore_errors=True)
        raise


def create_dataset_artifact(
    task_type: str, scene: str, include_ref: bool = False
) -> DatasetArtifact:
    task_type = normalize_task_type(task_type)
    scene = validate_storage_component(scene, "场景")
    prompt_path = _prompt_path(task_type, scene)
    if task_type == "T2I" or not include_ref:
        return DatasetArtifact(str(prompt_path), f"{scene}.txt", TXT_MEDIA_TYPE)
    parsed = parse_prompt_file_bytes(prompt_path.read_bytes())
    ref_files = _reference_files(task_type, scene, parsed["ids"])
    return _create_ti2i_archive(scene, prompt_path, ref_files)
