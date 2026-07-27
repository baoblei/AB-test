from collections.abc import Iterable
from typing import Optional

from .config import get_task_config, is_video_task
from .errors import AppError


def canonical_selected_dimensions(
    task_type: str, values: Optional[Iterable[str]]
) -> list[str]:
    if not is_video_task(task_type):
        raise AppError("图片任务不支持自定义评测维度")
    received = list(values or [])
    if not received:
        raise AppError("请至少选择一个评测维度")
    if len(received) != len(set(received)):
        raise AppError("评测维度不能重复")
    configured = list(get_task_config(task_type)["dashboard_dims"])
    if any(dimension not in configured for dimension in received):
        raise AppError("包含无效评测维度")
    selected = set(received)
    return [dimension for dimension in configured if dimension in selected]


def dimension_transition(previous: Iterable[str], current: Iterable[str]) -> str:
    old = set(previous)
    new = set(current)
    if old == new:
        return "equal"
    if old < new:
        return "superset"
    if new < old:
        return "subset"
    return "incomparable"
