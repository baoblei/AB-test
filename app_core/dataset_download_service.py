from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import normalize_task_type
from .errors import AppError
from .storage import (
    get_dataset_scenes,
    get_prompt_file_path,
    parse_prompt_file_bytes,
    validate_storage_component,
)

TXT_MEDIA_TYPE = "text/plain; charset=utf-8"


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


def create_dataset_artifact(
    task_type: str, scene: str, include_ref: bool = False
) -> DatasetArtifact:
    task_type = normalize_task_type(task_type)
    scene = validate_storage_component(scene, "场景")
    prompt_path = _prompt_path(task_type, scene)
    if task_type == "T2I" or not include_ref:
        return DatasetArtifact(str(prompt_path), f"{scene}.txt", TXT_MEDIA_TYPE)
    raise AppError("TI2I 参考图下载尚未实现")
