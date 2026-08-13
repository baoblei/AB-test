import csv
import sqlite3
from io import StringIO
from typing import Dict, List, Optional

from .bad_cases import build_bad_case_stats, safe_load_json_list
from .config import DIM_LABELS, get_task_config, normalize_task_type
from .database import connect
from .errors import InvalidDimensionError
from .storage import get_preview_prompt_text, get_ref_image_url


def fetch_result_rows(task_type: str, v_a: Optional[str] = None, v_b: Optional[str] = None, scene: Optional[str] = None):
    conn = connect(row_factory=True)
    cursor = conn.cursor()
    query = "SELECT * FROM results_log WHERE task_type=? AND skipped=0"
    params: List[object] = [normalize_task_type(task_type)]
    if v_a and v_b:
        query += " AND v_a=? AND v_b=?"
        params.extend([v_a, v_b])
    if scene:
        query += " AND scene=?"
        params.append(scene)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


def row_eval_mode(row) -> str:
    return row["eval_mode"] or "full"


def optional_row_value(row, key: str, default=None):
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def rows_for_dimension(rows: list[sqlite3.Row], dim: str) -> list[sqlite3.Row]:
    return [row for row in rows if optional_row_value(row, dim) is not None]


def active_dimensions(rows: list[sqlite3.Row], configured: list[str]) -> list[str]:
    return [
        dimension
        for dimension in configured
        if any(optional_row_value(row, dimension) is not None for row in rows)
    ]


def evaluator_identity(row):
    user_id = optional_row_value(row, "user_id")
    if user_id is not None:
        return ("user_id", user_id)
    return ("worker", optional_row_value(row, "worker"))


def sample_identity(row):
    v_a, v_b = sorted((row["v_a"], row["v_b"]))
    return (
        normalize_task_type(row["task_type"]),
        v_a,
        v_b,
        row["scene"],
        row["filename"],
    )


def build_conflict_index(rows, dimensions):
    vote_sides = {}
    for row in rows:
        sample_key = sample_identity(row)
        evaluator = evaluator_identity(row)
        canonical_a, canonical_b = sample_key[1], sample_key[2]
        for dimension in dimensions:
            value = optional_row_value(row, dimension)
            if value == canonical_a:
                side = "a"
            elif value == canonical_b:
                side = "b"
            else:
                continue
            sides = vote_sides.setdefault(
                (sample_key, dimension),
                {"a": set(), "b": set()},
            )
            sides[side].add(evaluator)

    conflicts = {}
    for (sample_key, dimension), sides in vote_sides.items():
        evaluators = sides["a"] | sides["b"]
        if sides["a"] and sides["b"] and len(evaluators) > 1:
            conflicts.setdefault(sample_key, set()).add(dimension)
    return conflicts


def dimension_stats(
    rows: list[sqlite3.Row],
    dim: str,
    v_a: str,
    v_b: str,
    *,
    conflict_index=None,
    exclude_conflicts: bool = False,
) -> dict:
    scored_rows = rows_for_dimension(rows, dim)
    if conflict_index is None:
        conflict_index = build_conflict_index(scored_rows, [dim])

    sample_keys = {sample_identity(row) for row in scored_rows}
    conflict_sample_keys = {
        key for key in sample_keys if dim in conflict_index.get(key, set())
    }
    aggregate_rows = scored_rows
    if exclude_conflicts:
        aggregate_rows = [
            row
            for row in scored_rows
            if sample_identity(row) not in conflict_sample_keys
        ]

    tie_bad_count = sum(1 for row in aggregate_rows if row[dim] == "tie_bad")
    tie_good_count = sum(1 for row in aggregate_rows if row[dim] == "tie_good")
    return {
        "total": len(aggregate_rows),
        "v_a_wins": sum(1 for row in aggregate_rows if row[dim] == v_a),
        "tie_bad_count": tie_bad_count,
        "tie_good_count": tie_good_count,
        "tie_count": tie_bad_count + tie_good_count,
        "v_b_wins": sum(1 for row in aggregate_rows if row[dim] == v_b),
        "sample_count": len(sample_keys),
        "conflict_sample_count": len(conflict_sample_keys),
    }


def aggregate_pair_rows(
    task_type: str,
    rows: Optional[list[sqlite3.Row]] = None,
    *,
    exclude_conflicts: bool = False,
    conflict_index=None,
) -> List[dict]:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    dashboard_dims = config["dashboard_dims"]
    rows = fetch_result_rows(task_type) if rows is None else list(rows)
    if conflict_index is None:
        conflict_index = build_conflict_index(rows, dashboard_dims)
    grouped: Dict[tuple, List[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault((row["v_a"], row["v_b"]), []).append(row)

    result = []
    for (v_a, v_b), pair_rows in sorted(grouped.items()):
        pair_dimensions = active_dimensions(pair_rows, dashboard_dims)
        pair_data = {
            "task_type": task_type,
            "pair": f"{v_a} vs {v_b}",
            "v_a": v_a,
            "v_b": v_b,
            "total": len(pair_rows),
            "active_dims": pair_dimensions,
            "dims": {},
            "bad_case": build_bad_case_stats(pair_rows),
            "scenes": [],
        }
        for dim in pair_dimensions:
            pair_data["dims"][dim] = dimension_stats(
                pair_rows,
                dim,
                v_a,
                v_b,
                conflict_index=conflict_index,
                exclude_conflicts=exclude_conflicts,
            )

        scene_grouped: Dict[str, List[sqlite3.Row]] = {}
        for row in pair_rows:
            scene_grouped.setdefault(row["scene"], []).append(row)
        for scene_name, scene_rows in sorted(scene_grouped.items()):
            scene_dimensions = active_dimensions(scene_rows, dashboard_dims)
            scene_data = {
                "scene": scene_name,
                "total": len(scene_rows),
                "active_dims": scene_dimensions,
                "dims": {},
                "bad_case": build_bad_case_stats(scene_rows),
            }
            for dim in scene_dimensions:
                scene_data["dims"][dim] = dimension_stats(
                    scene_rows,
                    dim,
                    v_a,
                    v_b,
                    conflict_index=conflict_index,
                    exclude_conflicts=exclude_conflicts,
                )
            pair_data["scenes"].append(scene_data)
        result.append(pair_data)
    return result


def dashboard_overview(task_type: str, exclude_conflicts: bool = False) -> dict:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    rows = fetch_result_rows(task_type)
    dimensions = active_dimensions(rows, config["dashboard_dims"])
    conflict_index = build_conflict_index(rows, config["dashboard_dims"])
    return {
        "task_type": task_type,
        "dims": [{"key": dim, "label": DIM_LABELS[dim]} for dim in dimensions],
        "pairs": aggregate_pair_rows(
            task_type,
            rows,
            exclude_conflicts=exclude_conflicts,
            conflict_index=conflict_index,
        ),
    }


def worker_stats(
    task_type: str,
    v1: str,
    v2: str,
    scene: Optional[str] = None,
    exclude_conflicts: bool = False,
) -> list[dict]:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    v_a, v_b = sorted([v1, v2])
    rows = fetch_result_rows(task_type, v_a, v_b, scene)
    conflict_index = build_conflict_index(rows, config["dashboard_dims"])
    grouped: Dict[str, List[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["worker"], []).append(row)

    result = []
    for worker, worker_rows in sorted(grouped.items()):
        dimensions = active_dimensions(worker_rows, config["dashboard_dims"])
        entry = {
            "worker": worker,
            "total": len(worker_rows),
            "active_dims": dimensions,
        }
        for dim in dimensions:
            entry[dim] = dimension_stats(
                worker_rows,
                dim,
                v_a,
                v_b,
                conflict_index=conflict_index,
                exclude_conflicts=exclude_conflicts,
            )
        result.append(entry)
    return result


def detail_results(task_type: str, v1: str, v2: str, scene: str) -> list[dict]:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    dimensions = config["dashboard_dims"]
    v_a, v_b = sorted([v1, v2])
    rows = fetch_result_rows(task_type, v_a, v_b, scene)
    rows = sorted(rows, key=lambda row: (row["worker"], row["filename"], row["timestamp"]), reverse=True)
    conflict_index = build_conflict_index(rows, dimensions)
    results = []
    for row in rows:
        conflicted = conflict_index.get(sample_identity(row), set())
        conflict_dimensions = [
            dimension for dimension in dimensions if dimension in conflicted
        ]
        results.append(
            {
                "task_type": task_type,
                "eval_mode": row_eval_mode(row),
                "scene": row["scene"],
                "filename": row["filename"],
                "overall": row["overall"],
                "aesthetic": row["aesthetic"],
                "logic": row["logic"],
                "consistency": row["consistency"],
                "fidelity": row["fidelity"],
                "text_consistency": optional_row_value(row, "text_consistency"),
                "structure_reasonableness": optional_row_value(
                    row, "structure_reasonableness"
                ),
                "motion_reasonableness": optional_row_value(
                    row, "motion_reasonableness"
                ),
                "dynamism": optional_row_value(row, "dynamism"),
                "physical_plausibility": optional_row_value(
                    row, "physical_plausibility"
                ),
                "visual_quality": optional_row_value(row, "visual_quality"),
                "image_consistency": optional_row_value(row, "image_consistency"),
                "selected_dimensions": safe_load_json_list(
                    optional_row_value(row, "selected_dimensions", "[]")
                ),
                "scores": {
                    dimension: optional_row_value(row, dimension)
                    for dimension in config["dashboard_dims"]
                },
                "worker": row["worker"],
                "time": row["timestamp"],
                "duration": row["duration_seconds"],
                "prompt": get_preview_prompt_text(
                    task_type, row["scene"], row["filename"]
                ),
                "ref_img": get_ref_image_url(
                    task_type, row["scene"], row["filename"]
                ),
                "bad_case_tags_a": safe_load_json_list(row["bad_case_tags_a"]),
                "bad_case_tags_b": safe_load_json_list(row["bad_case_tags_b"]),
                "has_conflict": bool(conflict_dimensions),
                "conflict_dimensions": conflict_dimensions,
            }
        )
    return results


def bad_case_details(
    task_type: str,
    v1: str,
    v2: str,
    scene: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
) -> dict:
    task_type = normalize_task_type(task_type)
    v_a, v_b = sorted([v1, v2])
    rows = fetch_result_rows(task_type, v_a, v_b, scene)
    results = []
    for row in sorted(rows, key=lambda item: item["timestamp"], reverse=True):
        prompt = get_preview_prompt_text(task_type, row["scene"], row["filename"])
        for model_name, tag_json, category_json in (
            (v_a, row["bad_case_tags_a"], row["bad_case_categories_a"]),
            (v_b, row["bad_case_tags_b"], row["bad_case_categories_b"]),
        ):
            tags = safe_load_json_list(tag_json)
            categories = safe_load_json_list(category_json)
            if not tags:
                continue
            if model and model != model_name:
                continue
            if category and category not in categories:
                continue
            if tag and tag not in tags:
                continue
            results.append(
                {
                    "task_type": task_type,
                    "scene": row["scene"],
                    "filename": row["filename"],
                    "model": model_name,
                    "worker": row["worker"],
                    "time": row["timestamp"],
                    "duration": row["duration_seconds"],
                    "prompt": prompt,
                    "categories": categories,
                    "tags": tags,
                    "ref_img": get_ref_image_url(task_type, row["scene"], row["filename"]),
                }
            )
    return {"results": results}


def export_results(format: str = "json", task_type: str = "T2I", v1: Optional[str] = None, v2: Optional[str] = None, scene: Optional[str] = None):
    task_type = normalize_task_type(task_type)
    query = "SELECT * FROM results_log WHERE task_type=? AND skipped=0"
    params: List[object] = [task_type]
    if v1 and v2:
        v_a, v_b = sorted([v1, v2])
        query += " AND v_a=? AND v_b=?"
        params.extend([v_a, v_b])
    if scene:
        query += " AND scene=?"
        params.append(scene)

    conn = connect()
    cursor = conn.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    conn.close()

    if format == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        writer.writerows(rows)
        return {"format": "csv", "data": output.getvalue()}
    return {"format": "json", "data": [dict(zip(columns, row)) for row in rows]}


def ranking(
    task_type: str = "T2I",
    scene: Optional[str] = None,
    dimension: str = "overall",
    exclude_conflicts: bool = False,
) -> list[dict]:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    if dimension not in config["dashboard_dims"]:
        raise InvalidDimensionError("无效维度")

    rows = rows_for_dimension(fetch_result_rows(task_type, scene=scene), dimension)
    conflict_index = build_conflict_index(rows, [dimension])
    if exclude_conflicts:
        rows = [
            row
            for row in rows
            if dimension not in conflict_index.get(sample_identity(row), set())
        ]
    stats: Dict[str, dict] = {}
    for row in rows:
        for model_name in (row["v_a"], row["v_b"]):
            stats.setdefault(model_name, {"wins": 0, "total": 0})
            stats[model_name]["total"] += 1
        if row[dimension] == row["v_a"]:
            stats[row["v_a"]]["wins"] += 1
        elif row[dimension] == row["v_b"]:
            stats[row["v_b"]]["wins"] += 1

    ranking_rows = []
    for model_name, entry in stats.items():
        total = entry["total"]
        ranking_rows.append(
            {
                "model": model_name,
                "wins": entry["wins"],
                "total": total,
                "win_rate": round(entry["wins"] / total * 100, 1) if total else 0,
            }
        )
    ranking_rows.sort(key=lambda item: item["win_rate"], reverse=True)
    return ranking_rows
