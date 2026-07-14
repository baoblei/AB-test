from typing import Iterable, Optional

from .bad_cases import safe_load_json_list
from .config import TASK_CONFIGS, dim_payload, normalize_task_type
from .database import connect
from .errors import AppError
from .schemas import ExportRequest
from .time_utils import is_canonical_beijing_iso


VALID_RESULT_FILTERS = {"all", "a", "tie", "b"}
VALID_BAD_CASE_FILTERS = {"all", "with", "without"}
VALID_EVAL_MODES = {"full", "overall"}


def canonical_models(request: ExportRequest) -> tuple[str, str]:
    return canonical_model_pair(request.v1, request.v2)


def canonical_model_pair(v1: str, v2: str) -> tuple[str, str]:
    if not v1 or not v1.strip() or not v2 or not v2.strip():
        raise AppError("模型名称不能为空")
    if v1 == v2:
        raise AppError("模型必须不同")
    return tuple(sorted((v1, v2)))


def validate_export_request(request: ExportRequest) -> tuple[str, str, str]:
    task_type = normalize_task_type(request.task_type)
    if task_type not in TASK_CONFIGS:
        raise AppError("无效任务类型")

    v_a, v_b = canonical_models(request)
    valid_dimensions = set(TASK_CONFIGS[task_type]["eval_dims"])
    if any(dimension not in valid_dimensions for dimension in request.dimensions):
        raise AppError("无效导出维度")
    if request.result_filter not in VALID_RESULT_FILTERS:
        raise AppError("无效结果筛选")
    if request.bad_case_filter not in VALID_BAD_CASE_FILTERS:
        raise AppError("无效坏例筛选")
    if any(mode not in VALID_EVAL_MODES for mode in request.eval_modes):
        raise AppError("无效评测模式")
    if request.start_time and not is_canonical_beijing_iso(request.start_time):
        raise AppError("导出时间必须为北京时间 ISO 格式")
    if request.end_time and not is_canonical_beijing_iso(request.end_time):
        raise AppError("导出时间必须为北京时间 ISO 格式")
    if request.start_time and request.end_time and request.start_time > request.end_time:
        raise AppError("开始时间不能晚于结束时间")
    return task_type, v_a, v_b


def expected_result(request: ExportRequest, v_a: Optional[str] = None, v_b: Optional[str] = None) -> Optional[str]:
    if v_a is None or v_b is None:
        v_a, v_b = canonical_models(request)
    return {"all": None, "a": v_a, "tie": "tie", "b": v_b}[request.result_filter]


def row_has_bad_case(row) -> bool:
    return bool(safe_load_json_list(row["bad_case_tags_a"]) or safe_load_json_list(row["bad_case_tags_b"]))


def filter_rows(rows: Iterable, request: ExportRequest, dimension: str) -> list:
    task_type, v_a, v_b = validate_export_request(request)
    if dimension != "overall" and dimension not in TASK_CONFIGS[task_type]["eval_dims"]:
        raise AppError("无效导出维度")

    wanted_result = expected_result(request, v_a, v_b)
    result = []
    for row in rows:
        if (
            row["task_type"] != task_type
            or row["v_a"] != v_a
            or row["v_b"] != v_b
            or row["skipped"]
        ):
            continue
        mode = row["eval_mode"] or "full"
        if request.scenes and row["scene"] not in request.scenes:
            continue
        if request.workers and row["worker"] not in request.workers:
            continue
        if request.eval_modes and mode not in request.eval_modes:
            continue
        if request.start_time and row["timestamp"] < request.start_time:
            continue
        if request.end_time and row["timestamp"] > request.end_time:
            continue
        has_bad_case = row_has_bad_case(row)
        if request.bad_case_filter == "with" and not has_bad_case:
            continue
        if request.bad_case_filter == "without" and has_bad_case:
            continue
        if dimension != "overall" and (mode != "full" or not row[dimension]):
            continue
        if wanted_result and row[dimension] != wanted_result:
            continue
        result.append(row)
    return result


def fetch_base_rows(task_type: str, v_a: str, v_b: str) -> list:
    conn = connect(row_factory=True)
    try:
        rows = conn.execute(
            """
            SELECT * FROM results_log
            WHERE task_type=? AND v_a=? AND v_b=? AND skipped=0
            """,
            (task_type, v_a, v_b),
        ).fetchall()
    finally:
        conn.close()
    return rows


def get_export_options(task_type: str, v1: str, v2: str) -> dict:
    normalized_task_type = normalize_task_type(task_type)
    if normalized_task_type not in TASK_CONFIGS:
        raise AppError("无效任务类型")
    v_a, v_b = canonical_model_pair(v1, v2)
    rows = fetch_base_rows(normalized_task_type, v_a, v_b)
    timestamps = [row["timestamp"] for row in rows]
    config = TASK_CONFIGS[normalized_task_type]
    return {
        "task_type": normalized_task_type,
        "v_a": v_a,
        "v_b": v_b,
        "scenes": sorted({row["scene"] for row in rows}),
        "workers": sorted({row["worker"] for row in rows}),
        "dimensions": dim_payload(config["eval_dims"]),
        "min_time": min(timestamps) if timestamps else None,
        "max_time": max(timestamps) if timestamps else None,
        "total": len(rows),
    }


def preview_export(request: ExportRequest) -> dict:
    task_type, v_a, v_b = validate_export_request(request)
    rows = fetch_base_rows(task_type, v_a, v_b)
    overall_rows = filter_rows(rows, request, "overall")
    dimension_rows = {
        dimension: filter_rows(rows, request, dimension) for dimension in request.dimensions
    }
    selected_rows = overall_rows + [row for rows_for_dimension in dimension_rows.values() for row in rows_for_dimension]
    unique_images = {(row["scene"], row["filename"]) for row in selected_rows}
    return {
        "overall": len(overall_rows),
        "dimensions": {dimension: len(items) for dimension, items in dimension_rows.items()},
        "unique_images": len(unique_images),
    }
