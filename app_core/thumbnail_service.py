"""Cached thumbnails for dashboard image lists."""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import is_video_task
from .errors import AppError, NotFoundError
from .storage import get_ref_image_path, get_result_image_path
from .video_media import extract_first_frame_webp


THUMBNAIL_CACHE_DIR = Path(".thumbnails")


def _resolve_source(
    kind: str,
    task_type: str,
    scene: str,
    filename: str,
    model: Optional[str],
) -> str:
    if kind == "result":
        if not model:
            raise AppError("结果图缩略图缺少模型")
        source = get_result_image_path(task_type, model, scene, filename)
    elif kind == "ref":
        source = get_ref_image_path(task_type, scene, filename)
    else:
        raise AppError("无效的缩略图类型")

    if not source:
        raise NotFoundError("图片不存在")
    return source


def _write_thumbnail(source: str, destination: Path, max_size: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix="thumbnail-",
        suffix=".webp",
    )
    os.close(descriptor)
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            image.save(temporary_name, format="WEBP", quality=82, method=4)
        os.replace(temporary_name, destination)
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise AppError("图片无法生成缩略图") from exc
    finally:
        try:
            os.remove(temporary_name)
        except FileNotFoundError:
            pass


def _write_video_thumbnail(source: str, destination: Path, max_size: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix="thumbnail-",
        suffix=".webp",
    )
    os.close(descriptor)
    try:
        Path(temporary_name).write_bytes(extract_first_frame_webp(source, max_size))
        os.replace(temporary_name, destination)
    except (OSError, ValueError) as exc:
        raise AppError("视频无法生成首帧缩略图") from exc
    finally:
        try:
            os.remove(temporary_name)
        except FileNotFoundError:
            pass


def get_image_thumbnail(
    kind: str,
    task_type: str,
    scene: str,
    filename: str,
    model: Optional[str] = None,
    cache_root: Path = THUMBNAIL_CACHE_DIR,
    max_size: int = 256,
) -> str:
    source = _resolve_source(kind, task_type, scene, filename, model)
    source_stat = os.stat(source)
    identity = "\0".join(
        (
            kind,
            task_type,
            model or "",
            scene,
            filename,
            str(source_stat.st_size),
            str(source_stat.st_mtime_ns),
        )
    )
    destination = Path(cache_root) / (
        hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".webp"
    )
    if destination.is_file():
        return os.fspath(destination)

    if kind == "result" and is_video_task(task_type):
        _write_video_thumbnail(source, destination, max_size)
    else:
        _write_thumbnail(source, destination, max_size)
    return os.fspath(destination)


def warm_result_thumbnail(
    task_type: str, model: str, scene: str, filename: str
) -> str:
    return get_image_thumbnail("result", task_type, scene, filename, model=model)
