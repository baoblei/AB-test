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


def rows_for_dimension(rows: list[sqlite3.Row], dim: str) -> list[sqlite3.Row]:
    if dim == "overall":
        return rows
    return [row for row in rows if row_eval_mode(row) == "full"]


def dimension_stats(rows: list[sqlite3.Row], dim: str, v_a: str, v_b: str) -> dict:
    scoped_rows = rows_for_dimension(rows, dim)
    return {
        "total": len(scoped_rows),
        "v_a_wins": sum(1 for row in scoped_rows if row[dim] == v_a),
        "v_b_wins": sum(1 for row in scoped_rows if row[dim] == v_b),
        "tie_count": sum(1 for row in scoped_rows if row[dim] == "tie"),
    }


def aggregate_pair_rows(task_type: str) -> List[dict]:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    dashboard_dims = config["dashboard_dims"]
    rows = fetch_result_rows(task_type)
    grouped: Dict[tuple, List[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault((row["v_a"], row["v_b"]), []).append(row)

    result = []
    for (v_a, v_b), pair_rows in sorted(grouped.items()):
        pair_data = {
            "task_type": task_type,
            "pair": f"{v_a} vs {v_b}",
            "v_a": v_a,
            "v_b": v_b,
            "total": len(pair_rows),
            "dims": {},
            "bad_case": build_bad_case_stats(pair_rows),
            "scenes": [],
        }
        for dim in dashboard_dims:
            pair_data["dims"][dim] = dimension_stats(pair_rows, dim, v_a, v_b)

        scene_grouped: Dict[str, List[sqlite3.Row]] = {}
        for row in pair_rows:
            scene_grouped.setdefault(row["scene"], []).append(row)
        for scene_name, scene_rows in sorted(scene_grouped.items()):
            scene_data = {
                "scene": scene_name,
                "total": len(scene_rows),
                "dims": {},
                "bad_case": build_bad_case_stats(scene_rows),
            }
            for dim in dashboard_dims:
                scene_data["dims"][dim] = dimension_stats(scene_rows, dim, v_a, v_b)
            pair_data["scenes"].append(scene_data)
        result.append(pair_data)
    return result


def dashboard_overview(task_type: str) -> dict:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    return {
        "task_type": task_type,
        "dims": [{"key": dim, "label": DIM_LABELS[dim]} for dim in config["dashboard_dims"]],
        "pairs": aggregate_pair_rows(task_type),
    }


def worker_stats(task_type: str, v1: str, v2: str, scene: Optional[str] = None) -> list[dict]:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    v_a, v_b = sorted([v1, v2])
    rows = fetch_result_rows(task_type, v_a, v_b, scene)
    grouped: Dict[str, List[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["worker"], []).append(row)

    result = []
    for worker, worker_rows in sorted(grouped.items()):
        entry = {"worker": worker, "total": len(worker_rows)}
        for dim in config["dashboard_dims"]:
            entry[dim] = dimension_stats(worker_rows, dim, v_a, v_b)
        result.append(entry)
    return result


def detail_results(task_type: str, v1: str, v2: str, scene: str) -> list[dict]:
    task_type = normalize_task_type(task_type)
    v_a, v_b = sorted([v1, v2])
    rows = fetch_result_rows(task_type, v_a, v_b, scene)
    rows = sorted(rows, key=lambda row: (row["worker"], row["filename"], row["timestamp"]), reverse=True)
    return [
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
            "worker": row["worker"],
            "time": row["timestamp"],
            "duration": row["duration_seconds"],
            "prompt": get_preview_prompt_text(task_type, row["scene"], row["filename"]),
            "ref_img": get_ref_image_url(task_type, row["scene"], row["filename"]),
            "bad_case_tags_a": safe_load_json_list(row["bad_case_tags_a"]),
            "bad_case_tags_b": safe_load_json_list(row["bad_case_tags_b"]),
        }
        for row in rows
    ]


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


def ranking(task_type: str = "T2I", scene: Optional[str] = None, dimension: str = "overall") -> list[dict]:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    if dimension not in config["dashboard_dims"]:
        raise InvalidDimensionError("无效维度")

    rows = rows_for_dimension(fetch_result_rows(task_type, scene=scene), dimension)
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
