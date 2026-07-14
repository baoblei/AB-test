import json
import os
import random
from typing import Any, Optional

from .bad_cases import categories_from_tags, derive_overall_result, normalize_bad_case_tags
from .config import get_task_config, normalize_task_type
from .database import connect
from .errors import AppError, NotFoundError
from .storage import get_prompt_text, get_ref_image_url, get_result_image_url, get_scene_path, list_scene_files
from .time_utils import now_beijing_iso


def normalize_eval_mode(eval_mode: Optional[str]) -> str:
    mode = (eval_mode or "full").lower()
    if mode not in ("full", "overall"):
        raise AppError("无效评测模式")
    return mode


def evaluation_scope(task_type: str, worker: str, v1: str, v2: str, scene: str) -> tuple[str, str, str]:
    task_type = normalize_task_type(task_type)
    v_a, v_b = sorted([v1, v2])
    return task_type, v_a, v_b


def get_eval_mode_status(task_type: str, worker: str, v1: str, v2: str, scene: str) -> dict:
    task_type, v_a, v_b = evaluation_scope(task_type, worker, v1, v2, scene)
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT eval_mode, skipped, COUNT(*)
        FROM results_log
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND worker=?
        GROUP BY eval_mode, skipped
        """,
        (task_type, v_a, v_b, scene, worker),
    )
    rows = cursor.fetchall()
    conn.close()

    status = {
        "task_type": task_type,
        "v_a": v_a,
        "v_b": v_b,
        "scene": scene,
        "worker": worker,
        "full_count": 0,
        "full_total": 0,
        "overall_count": 0,
        "overall_total": 0,
    }
    for eval_mode, skipped, count in rows:
        mode = eval_mode or "full"
        if mode == "overall":
            status["overall_total"] += count
            if not skipped:
                status["overall_count"] += count
        else:
            status["full_total"] += count
            if not skipped:
                status["full_count"] += count

    status["can_overall"] = status["full_count"] == 0
    status["needs_full_overwrite_confirmation"] = status["overall_total"] > 0 and status["full_count"] == 0
    return status


def reset_pair_tasks(task_type: str, worker: str, v_a: str, v_b: str, scene: str, user_id: int):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE pair_tasks
        SET status='pending', assigned_user_id=?
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND worker=?
        """,
        (user_id, task_type, v_a, v_b, scene, worker),
    )
    conn.commit()
    conn.close()


def delete_eval_rows(task_type: str, worker: str, v_a: str, v_b: str, scene: str, eval_mode: str):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        DELETE FROM results_log
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND worker=? AND eval_mode=?
        """,
        (task_type, v_a, v_b, scene, worker, eval_mode),
    )
    conn.commit()
    conn.close()


def start_eval_session(
    task_type: str,
    worker: str,
    v1: str,
    v2: str,
    scene: str,
    eval_mode: str,
    user_id: int,
    overwrite_overall: bool = False,
) -> dict:
    mode = normalize_eval_mode(eval_mode)
    status = get_eval_mode_status(task_type, worker, v1, v2, scene)
    task_type = status["task_type"]
    v_a = status["v_a"]
    v_b = status["v_b"]

    if mode == "overall":
        if status["full_count"] > 0:
            raise AppError("当前模型对和场景已进行过多维度评测，无法再进行整体单一维度评测")
        if status["full_total"] > 0 and status["overall_total"] == 0:
            delete_eval_rows(task_type, worker, v_a, v_b, scene, "full")
            reset_pair_tasks(task_type, worker, v_a, v_b, scene, user_id)
        return {"status": "ok", "eval_mode": mode, "mode_status": get_eval_mode_status(task_type, worker, v_a, v_b, scene)}

    if status["overall_total"] > 0 and status["full_count"] == 0:
        if not overwrite_overall:
            return {
                "status": "requires_confirmation",
                "message": "当前模型对和场景已有整体单一维度评测结果，继续多维度评测会覆盖这些整体评测结果。",
                "mode_status": status,
            }
        delete_eval_rows(task_type, worker, v_a, v_b, scene, "overall")
        if status["full_total"] > 0 and status["full_count"] == 0:
            delete_eval_rows(task_type, worker, v_a, v_b, scene, "full")
        reset_pair_tasks(task_type, worker, v_a, v_b, scene, user_id)

    return {"status": "ok", "eval_mode": mode, "mode_status": get_eval_mode_status(task_type, worker, v_a, v_b, scene)}


def ensure_pair_tasks(task_type: str, worker: str, v_a: str, v_b: str, scene: str, user_id: int):
    conn = connect()
    cursor = conn.cursor()
    for filename in list_scene_files(task_type, v_a, scene):
        if os.path.exists(os.path.join(get_scene_path(task_type, v_b, scene), filename)):
            cursor.execute(
                """
                INSERT OR IGNORE INTO pair_tasks (task_type, v_a, v_b, scene, filename, worker, assigned_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_type, v_a, v_b, scene, filename, worker, user_id),
            )
    conn.commit()
    conn.close()


def get_next_task(task_type: str, worker: str, v1: str, v2: str, scene: str, user_id: int) -> dict:
    task_type = normalize_task_type(task_type)
    get_task_config(task_type)
    v_a, v_b = sorted([v1, v2])
    ensure_pair_tasks(task_type, worker, v_a, v_b, scene, user_id)

    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, filename FROM pair_tasks
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND status='working' AND worker=?
        LIMIT 1
        """,
        (task_type, v_a, v_b, scene, worker),
    )
    row = cursor.fetchone()
    if not row:
        cursor.execute("BEGIN EXCLUSIVE TRANSACTION")
        cursor.execute(
            """
            SELECT id, filename FROM pair_tasks
            WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND status='pending' AND worker=?
            """,
            (task_type, v_a, v_b, scene, worker),
        )
        pending = cursor.fetchall()
        row = random.choice(pending) if pending else None
        if row:
            cursor.execute("UPDATE pair_tasks SET status='working' WHERE id=?", (row[0],))
            conn.commit()
        else:
            conn.rollback()
    conn.close()
    if not row:
        return {"status": "finished"}

    display = [v_a, v_b]
    random.shuffle(display)
    filename = row[1]
    return {
        "task_type": task_type,
        "task_id": row[0],
        "scene": scene,
        "filename": filename,
        "prompt": get_prompt_text(task_type, scene, filename),
        "left_img": get_result_image_url(task_type, display[0], scene, filename),
        "right_img": get_result_image_url(task_type, display[1], scene, filename),
        "v_left": display[0],
        "v_right": display[1],
        "show_ref": bool(get_task_config(task_type)["show_ref"]),
        "ref_img": get_ref_image_url(task_type, scene, filename),
    }


def get_progress(task_type: str, worker: str, v1: str, v2: str, scene: str, eval_mode: str = "full") -> dict:
    task_type = normalize_task_type(task_type)
    eval_mode = normalize_eval_mode(eval_mode)
    v_a, v_b = sorted([v1, v2])
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM pair_tasks WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND worker=?",
        (task_type, v_a, v_b, scene, worker),
    )
    total = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT COUNT(*) FROM pair_tasks
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND worker=? AND status='completed'
        """,
        (task_type, v_a, v_b, scene, worker),
    )
    completed = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT COUNT(*) FROM results_log
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND worker=? AND skipped=1 AND eval_mode=?
        """,
        (task_type, v_a, v_b, scene, worker, eval_mode),
    )
    skipped = cursor.fetchone()[0]
    conn.close()
    percent = round((completed + skipped) / total * 100, 1) if total else 0
    return {
        "total": total,
        "completed": completed,
        "skipped": skipped,
        "remaining": max(total - completed - skipped, 0),
        "percent": percent,
    }


def submit_vote(vote: Any, user_id: int) -> dict:
    task_type = normalize_task_type(vote.task_type)
    eval_mode = normalize_eval_mode(getattr(vote, "eval_mode", "full"))
    config = get_task_config(task_type)

    def resolve(choice: Optional[str]) -> str:
        if choice == "left":
            return vote.v_left
        if choice == "right":
            return vote.v_right
        return "tie"

    left_tags = normalize_bad_case_tags(vote.bad_case_left)
    right_tags = normalize_bad_case_tags(vote.bad_case_right)
    if vote.v_left < vote.v_right:
        tags_a, tags_b = left_tags, right_tags
    else:
        tags_a, tags_b = right_tags, left_tags

    v_a, v_b = sorted([vote.v_left, vote.v_right])
    if eval_mode == "overall":
        mode_status = get_eval_mode_status(task_type, vote.worker, v_a, v_b, vote.scene)
        if mode_status["full_count"] > 0:
            raise AppError("当前模型对和场景已进行过多维度评测，无法提交整体单一维度评测")
        overall = resolve(vote.overall)
        dim_values = {"aesthetic": None, "logic": None, "consistency": None, "fidelity": None}
    else:
        missing_dims = [dim for dim in config["eval_dims"] if not getattr(vote, dim, None)]
        if missing_dims:
            raise AppError("请完成所有评分维度")
        dim_values = {
            "aesthetic": resolve(vote.aesthetic),
            "logic": resolve(vote.logic),
            "consistency": resolve(vote.consistency),
            "fidelity": resolve(vote.fidelity) if "fidelity" in config["eval_dims"] else "tie",
        }
        overall = derive_overall_result([dim_values[dim] for dim in config["eval_dims"]])

    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO results_log (
            eval_mode, task_type, v_a, v_b, scene, filename, overall, aesthetic, logic, consistency, fidelity,
            worker, timestamp, duration_seconds, user_id,
            bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            eval_mode,
            task_type,
            v_a,
            v_b,
            vote.scene,
            vote.filename,
            overall,
            dim_values["aesthetic"],
            dim_values["logic"],
            dim_values["consistency"],
            dim_values["fidelity"],
            vote.worker,
            now_beijing_iso(),
            vote.duration_seconds,
            user_id,
            json.dumps(tags_a, ensure_ascii=False),
            json.dumps(tags_b, ensure_ascii=False),
            json.dumps(categories_from_tags(tags_a), ensure_ascii=False),
            json.dumps(categories_from_tags(tags_b), ensure_ascii=False),
        ),
    )
    cursor.execute("UPDATE pair_tasks SET status='completed' WHERE id=?", (vote.task_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}


def skip_task(task_id: int, task_type: str, user_id: int, eval_mode: str = "full") -> dict:
    task_type = normalize_task_type(task_type)
    eval_mode = normalize_eval_mode(eval_mode)
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT v_a, v_b, scene, filename, worker FROM pair_tasks WHERE id=? AND task_type=?",
        (task_id, task_type),
    )
    task = cursor.fetchone()
    if not task:
        conn.close()
        raise NotFoundError("任务不存在")

    cursor.execute(
        """
        INSERT INTO results_log (
            eval_mode, task_type, v_a, v_b, scene, filename, overall, aesthetic, logic, consistency, fidelity,
            worker, timestamp, skipped, user_id,
            bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
        )
        VALUES (?, ?, ?, ?, ?, ?, 'skipped', 'skipped', 'skipped', 'skipped', 'skipped', ?, ?, 1, ?, '[]', '[]', '[]', '[]')
        """,
        (eval_mode, task_type, task[0], task[1], task[2], task[3], task[4], now_beijing_iso(), user_id),
    )
    cursor.execute("UPDATE pair_tasks SET status='completed' WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}
