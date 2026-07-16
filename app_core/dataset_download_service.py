from __future__ import annotations

import errno
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .config import IMAGE_EXTENSIONS, normalize_task_type
from .errors import AppError
from .storage import (
    get_dataset_scenes,
    get_prompt_root,
    get_ref_root,
    parse_prompt_file_bytes,
    validate_storage_component,
)

TXT_MEDIA_TYPE = "text/plain; charset=utf-8"
ZIP_MEDIA_TYPE = "application/zip"
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class DatasetArtifact:
    path: str
    filename: str
    media_type: str
    cleanup_dir: str | None = None


def _open_directory(path: str | Path, error: str) -> int:
    """Open every path component without following symlinks."""
    absolute = Path(path).absolute()
    descriptor = os.open(os.sep, _DIRECTORY_FLAGS)
    try:
        for component in absolute.parts[1:]:
            next_descriptor = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise AppError(error) from exc


def _read_regular_at(directory_fd: int, filename: str, error: str, unsafe_error: str | None = None) -> bytes:
    try:
        before = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise AppError(unsafe_error or error)
        descriptor = os.open(filename, _FILE_FLAGS, dir_fd=directory_fd)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise AppError(unsafe_error or error)
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                return source.read()
        finally:
            os.close(descriptor)
    except AppError:
        raise
    except OSError as exc:
        raise AppError(error) from exc


def _prompt_bytes(task_type: str, scene: str) -> bytes:
    error = f"未找到场景 {scene} 的 prompt 文件"
    root_fd = _open_directory(get_prompt_root(task_type), "prompt 路径不安全")
    try:
        return _read_regular_at(root_fd, f"{scene}.txt", error, "prompt 路径不安全")
    finally:
        os.close(root_fd)


def list_datasets(task_type: str) -> list[dict]:
    task_type = normalize_task_type(task_type)
    datasets = []
    for scene in get_dataset_scenes(task_type):
        scene = validate_storage_component(scene, "场景")
        parsed = parse_prompt_file_bytes(_prompt_bytes(task_type, scene))
        datasets.append({"scene": scene, "prompt_count": parsed["count"]})
    return datasets


def _open_reference_scene(task_type: str, scene: str, prompt_ids: list[str]) -> tuple[int, list[str]]:
    root_fd = _open_directory(get_ref_root(task_type), "参考图目录包含不安全文件")
    try:
        scene_fd = os.open(scene, _DIRECTORY_FLAGS, dir_fd=root_fd)
    except OSError as exc:
        message = f"未找到场景 {scene} 的参考图" if exc.errno == errno.ENOENT else "参考图目录包含不安全文件"
        raise AppError(message) from exc
    finally:
        os.close(root_fd)
    try:
        names = []
        for name in os.listdir(scene_fd):
            if Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            info = os.stat(name, dir_fd=scene_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise AppError("参考图目录包含不安全文件")
            names.append(name)
        stems = [Path(name).stem for name in names]
        if len(stems) != len(set(stems)):
            raise AppError("参考图存在重复图片 ID")
        missing = sorted(set(prompt_ids) - set(stems))
        extra = sorted(set(stems) - set(prompt_ids))
        if missing or extra:
            raise AppError(f"参考图和 prompt 不匹配：缺少 {len(missing)} 个，多出 {len(extra)} 个")
        return scene_fd, sorted(names)
    except Exception:
        os.close(scene_fd)
        raise


def _create_txt_artifact(scene: str, prompt_bytes: bytes) -> DatasetArtifact:
    cleanup_dir = tempfile.mkdtemp(prefix="ab-test-dataset-")
    path = Path(cleanup_dir) / f"{scene}.txt"
    try:
        path.write_bytes(prompt_bytes)
        return DatasetArtifact(str(path), f"{scene}.txt", TXT_MEDIA_TYPE, cleanup_dir)
    except Exception:
        shutil.rmtree(cleanup_dir, ignore_errors=True)
        raise


def _create_ti2i_archive(scene: str, prompt_bytes: bytes, scene_fd: int, ref_names: list[str]) -> DatasetArtifact:
    cleanup_dir = tempfile.mkdtemp(prefix="ab-test-dataset-")
    archive_path = Path(cleanup_dir) / f"{scene}.zip"
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{scene}.txt", prompt_bytes)
            for name in ref_names:
                archive.writestr(f"ref_images/{name}", _read_regular_at(scene_fd, name, "参考图目录包含不安全文件"))
        return DatasetArtifact(str(archive_path), f"{scene}.zip", ZIP_MEDIA_TYPE, cleanup_dir)
    except Exception:
        shutil.rmtree(cleanup_dir, ignore_errors=True)
        raise


def create_dataset_artifact(task_type: str, scene: str, include_ref: bool = False) -> DatasetArtifact:
    task_type = normalize_task_type(task_type)
    scene = validate_storage_component(scene, "场景")
    prompt_bytes = _prompt_bytes(task_type, scene)
    if task_type == "T2I" or not include_ref:
        return _create_txt_artifact(scene, prompt_bytes)
    parsed = parse_prompt_file_bytes(prompt_bytes)
    scene_fd, ref_names = _open_reference_scene(task_type, scene, parsed["ids"])
    try:
        return _create_ti2i_archive(scene, prompt_bytes, scene_fd, ref_names)
    finally:
        os.close(scene_fd)
