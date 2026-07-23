import json
import os
import random
from typing import Any, Optional

from .bad_cases import categories_from_tags, derive_overall_result, normalize_bad_case_tags
from .config import get_task_config, normalize_task_type
from .database import connect
from .errors import AppError, ConflictError
from .storage import get_preview_prompt_text, get_ref_image_url, get_result_image_url, get_scene_path, list_scene_files
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


def _get_eval_mode_status(
    cursor,
    task_type: str,
    worker: str,
    v_a: str,
    v_b: str,
    scene: str,
    user_id: int,
) -> dict:
    cursor.execute(
        """
        SELECT eval_mode, skipped, COUNT(*)
        FROM results_log
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND user_id=?
        GROUP BY eval_mode, skipped
        """,
        (task_type, v_a, v_b, scene, user_id),
    )
    rows = cursor.fetchall()
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
    status["needs_full_overwrite_confirmation"] = status["overall_total"] > 0
    return status


def get_eval_mode_status(
    task_type: str,
    worker: str,
    v1: str,
    v2: str,
    scene: str,
    user_id: int,
) -> dict:
    task_type, v_a, v_b = evaluation_scope(task_type, worker, v1, v2, scene)
    conn = connect()
    try:
        return _get_eval_mode_status(conn.cursor(), task_type, worker, v_a, v_b, scene, user_id)
    finally:
        conn.close()


def _available_pair_files(task_type: str, v_a: str, v_b: str, scene: str) -> list[str]:
    return [
        filename
        for filename in list_scene_files(task_type, v_a, scene)
        if os.path.exists(os.path.join(get_scene_path(task_type, v_b, scene), filename))
    ]


def _claim_pair_task(
    cursor,
    task_type: str,
    worker: str,
    v_a: str,
    v_b: str,
    scene: str,
    filename: str,
    user_id: int,
    eval_mode: str,
    align_mode: bool,
) -> None:
    cursor.execute(
        """
        SELECT id, assigned_user_id
        FROM pair_tasks
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND filename=?
          AND (
              assigned_user_id=?
              OR (
                  worker=?
                  AND (
                      assigned_user_id IS NULL
                      OR NOT EXISTS (SELECT 1 FROM users WHERE users.id=pair_tasks.assigned_user_id)
                  )
              )
          )
        ORDER BY CASE WHEN assigned_user_id=? THEN 0 ELSE 1 END, id
        """,
        (task_type, v_a, v_b, scene, filename, user_id, worker, user_id),
    )
    candidates = cursor.fetchall()
    if not candidates:
        storage_worker = worker
        suffix = 0
        while cursor.execute(
            """
            SELECT 1 FROM pair_tasks
            WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND filename=? AND worker=?
            """,
            (task_type, v_a, v_b, scene, filename, storage_worker),
        ).fetchone():
            suffix += 1
            storage_worker = f"{worker}#{user_id}" if suffix == 1 else f"{worker}#{user_id}-{suffix}"
        cursor.execute(
            """
            INSERT INTO pair_tasks
            (task_type, v_a, v_b, scene, filename, status, eval_mode, worker, assigned_user_id)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (task_type, v_a, v_b, scene, filename, eval_mode, storage_worker, user_id),
        )
        return

    task_id = candidates[0][0]
    for duplicate_id, _owner_id in candidates[1:]:
        cursor.execute("UPDATE results_log SET task_id=NULL WHERE task_id=?", (duplicate_id,))
        cursor.execute("DELETE FROM pair_tasks WHERE id=?", (duplicate_id,))

    worker_conflict = cursor.execute(
        """
        SELECT 1 FROM pair_tasks
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND filename=?
          AND worker=? AND id<>?
        """,
        (task_type, v_a, v_b, scene, filename, worker, task_id),
    ).fetchone()
    worker_update = "worker=?, " if not worker_conflict else ""
    worker_params = (worker,) if not worker_conflict else ()
    if align_mode:
        cursor.execute(
            f"UPDATE pair_tasks SET {worker_update}assigned_user_id=?, eval_mode=? WHERE id=?",
            (*worker_params, user_id, eval_mode, task_id),
        )
    else:
        cursor.execute(
            f"UPDATE pair_tasks SET {worker_update}assigned_user_id=? WHERE id=?",
            (*worker_params, user_id, task_id),
        )


def _ensure_pair_tasks(
    cursor,
    task_type: str,
    worker: str,
    v_a: str,
    v_b: str,
    scene: str,
    user_id: int,
    eval_mode: str,
    filenames: list[str],
    align_mode: bool = False,
) -> None:
    for filename in filenames:
        _claim_pair_task(
            cursor,
            task_type,
            worker,
            v_a,
            v_b,
            scene,
            filename,
            user_id,
            eval_mode,
            align_mode,
        )


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
    task_type, v_a, v_b = evaluation_scope(task_type, worker, v1, v2, scene)
    get_task_config(task_type)
    available_files = _available_pair_files(task_type, v_a, v_b, scene)
    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        status = _get_eval_mode_status(cursor, task_type, worker, v_a, v_b, scene, user_id)

        if mode == "overall" and status["full_count"] > 0:
            raise AppError("当前模型对和场景已进行过多维度评测，无法再进行整体单一维度评测")
        if mode == "full" and status["overall_total"] > 0 and not overwrite_overall:
            conn.commit()
            return {
                "status": "requires_confirmation",
                "message": "当前模型对和场景已有整体单一维度评测结果，继续多维度评测会覆盖这些整体评测结果。",
                "mode_status": status,
            }

        opposite_mode = "full" if mode == "overall" else "overall"
        cursor.execute(
            """
            DELETE FROM results_log
            WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND user_id=? AND eval_mode=?
            """,
            (task_type, v_a, v_b, scene, user_id, opposite_mode),
        )
        cursor.execute(
            """
            SELECT filename, eval_mode FROM pair_tasks
            WHERE task_type=? AND v_a=? AND v_b=? AND scene=?
              AND (
                  assigned_user_id=?
                  OR (
                      worker=?
                      AND (
                          assigned_user_id IS NULL
                          OR NOT EXISTS (SELECT 1 FROM users WHERE users.id=pair_tasks.assigned_user_id)
                      )
                  )
              )
            """,
            (task_type, v_a, v_b, scene, user_id, worker),
        )
        known_tasks = cursor.fetchall()
        known_files = {row[0] for row in known_tasks}
        requires_task_reset = (
            status[f"{opposite_mode}_total"] > 0
            or any((task_mode or "full") != mode for _filename, task_mode in known_tasks)
        )
        _ensure_pair_tasks(
            cursor,
            task_type,
            worker,
            v_a,
            v_b,
            scene,
            user_id,
            mode,
            sorted(set(available_files) | known_files),
            align_mode=True,
        )
        if requires_task_reset:
            cursor.execute(
                """
                UPDATE pair_tasks
                SET status='pending', eval_mode=?
                WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND assigned_user_id=?
                """,
                (mode, task_type, v_a, v_b, scene, user_id),
            )
        cursor.execute(
            """
            UPDATE pair_tasks
            SET status='completed'
            WHERE task_type=? AND v_a=? AND v_b=? AND scene=?
              AND assigned_user_id=? AND eval_mode=?
              AND EXISTS (
                  SELECT 1 FROM results_log
                  WHERE results_log.task_type=pair_tasks.task_type
                    AND results_log.v_a=pair_tasks.v_a
                    AND results_log.v_b=pair_tasks.v_b
                    AND results_log.scene=pair_tasks.scene
                    AND results_log.filename=pair_tasks.filename
                    AND results_log.user_id=?
                    AND results_log.eval_mode=?
                    AND (results_log.task_id=pair_tasks.id OR results_log.task_id IS NULL)
              )
            """,
            (task_type, v_a, v_b, scene, user_id, mode, user_id, mode),
        )
        updated_status = _get_eval_mode_status(cursor, task_type, worker, v_a, v_b, scene, user_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"status": "ok", "eval_mode": mode, "mode_status": updated_status}


def ensure_pair_tasks(
    task_type: str,
    worker: str,
    v_a: str,
    v_b: str,
    scene: str,
    user_id: int,
    eval_mode: str = "full",
):
    mode = normalize_eval_mode(eval_mode)
    filenames = _available_pair_files(task_type, v_a, v_b, scene)
    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        _ensure_pair_tasks(cursor, task_type, worker, v_a, v_b, scene, user_id, mode, filenames)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_next_task(
    task_type: str,
    worker: str,
    v1: str,
    v2: str,
    scene: str,
    user_id: int,
    eval_mode: str = "full",
) -> dict:
    task_type = normalize_task_type(task_type)
    mode = normalize_eval_mode(eval_mode)
    get_task_config(task_type)
    v_a, v_b = sorted([v1, v2])
    ensure_pair_tasks(task_type, worker, v_a, v_b, scene, user_id, mode)

    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            SELECT id, filename FROM pair_tasks
            WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND status='working'
              AND assigned_user_id=? AND eval_mode=?
            LIMIT 1
            """,
            (task_type, v_a, v_b, scene, user_id, mode),
        )
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                """
                SELECT id, filename FROM pair_tasks
                WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND status='pending'
                  AND assigned_user_id=? AND eval_mode=?
                """,
                (task_type, v_a, v_b, scene, user_id, mode),
            )
            pending = cursor.fetchall()
            row = random.choice(pending) if pending else None
            if row:
                cursor.execute(
                    """
                    UPDATE pair_tasks SET status='working'
                    WHERE id=? AND status='pending' AND assigned_user_id=? AND eval_mode=?
                    """,
                    (row[0], user_id, mode),
                )
                if cursor.rowcount != 1:
                    raise ConflictError("任务领取冲突，请重试")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if not row:
        return {"status": "finished"}

    display = [v_a, v_b]
    random.shuffle(display)
    filename = row[1]
    return {
        "task_type": task_type,
        "eval_mode": mode,
        "task_id": row[0],
        "scene": scene,
        "filename": filename,
        "prompt": get_preview_prompt_text(task_type, scene, filename),
        "left_img": get_result_image_url(task_type, display[0], scene, filename),
        "right_img": get_result_image_url(task_type, display[1], scene, filename),
        "v_left": display[0],
        "v_right": display[1],
        "show_ref": bool(get_task_config(task_type)["show_ref"]),
        "ref_img": get_ref_image_url(task_type, scene, filename),
    }


def get_progress(
    task_type: str,
    worker: str,
    v1: str,
    v2: str,
    scene: str,
    eval_mode: str = "full",
    user_id: Optional[int] = None,
) -> dict:
    task_type = normalize_task_type(task_type)
    eval_mode = normalize_eval_mode(eval_mode)
    if user_id is None:
        raise AppError("缺少评测用户")
    v_a, v_b = sorted([v1, v2])
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) FROM pair_tasks
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND assigned_user_id=? AND eval_mode=?
        """,
        (task_type, v_a, v_b, scene, user_id, eval_mode),
    )
    total = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT COUNT(*) FROM pair_tasks
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND assigned_user_id=?
          AND eval_mode=? AND status='completed'
        """,
        (task_type, v_a, v_b, scene, user_id, eval_mode),
    )
    completed_tasks = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT COUNT(*) FROM pair_tasks AS current_task
        WHERE current_task.task_type=?
          AND current_task.v_a=?
          AND current_task.v_b=?
          AND current_task.scene=?
          AND current_task.assigned_user_id=?
          AND current_task.eval_mode=?
          AND current_task.status='completed'
          AND EXISTS (
              SELECT 1 FROM results_log
              WHERE results_log.task_type=current_task.task_type
                AND results_log.v_a=current_task.v_a
                AND results_log.v_b=current_task.v_b
                AND results_log.scene=current_task.scene
                AND results_log.filename=current_task.filename
                AND results_log.user_id=current_task.assigned_user_id
                AND results_log.eval_mode=current_task.eval_mode
                AND results_log.skipped=1
                AND (
                    results_log.task_id=current_task.id
                    OR (results_log.task_id IS NULL AND results_log.filename=current_task.filename)
                )
          )
        """,
        (task_type, v_a, v_b, scene, user_id, eval_mode),
    )
    skipped = cursor.fetchone()[0]
    conn.close()
    completed = max(completed_tasks - skipped, 0)
    percent = min(round(completed_tasks / total * 100, 1), 100.0) if total else 0
    return {
        "total": total,
        "completed": completed,
        "skipped": skipped,
        "remaining": max(total - completed_tasks, 0),
        "percent": percent,
    }


def _get_owned_working_task(cursor, task_id: int, task_type: str, user_id: int):
    cursor.execute(
        """
        SELECT v_a, v_b, scene, filename, worker, eval_mode
        FROM pair_tasks
        WHERE id=? AND task_type=? AND status='working' AND assigned_user_id=?
        """,
        (task_id, task_type, user_id),
    )
    task = cursor.fetchone()
    if not task:
        raise ConflictError("任务已完成、已失效或不属于当前用户")
    return task


def _complete_owned_task(cursor, task_id: int, user_id: int, eval_mode: str) -> None:
    cursor.execute(
        """
        UPDATE pair_tasks SET status='completed'
        WHERE id=? AND status='working' AND assigned_user_id=? AND eval_mode=?
        """,
        (task_id, user_id, eval_mode),
    )
    if cursor.rowcount != 1:
        raise ConflictError("任务已完成、已失效或不属于当前用户")


def _ensure_result_mode_exclusive(
    cursor,
    task_type: str,
    v_a: str,
    v_b: str,
    scene: str,
    user_id: int,
    eval_mode: str,
) -> None:
    opposite_mode = "full" if eval_mode == "overall" else "overall"
    cursor.execute(
        """
        SELECT 1 FROM results_log
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND user_id=? AND eval_mode=?
        LIMIT 1
        """,
        (task_type, v_a, v_b, scene, user_id, opposite_mode),
    )
    if cursor.fetchone():
        raise ConflictError("评测模式已变化，请重新进入评测")


def submit_vote(vote: Any, user_id: int, worker: str) -> dict:
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
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        task = _get_owned_working_task(cursor, vote.task_id, task_type, user_id)
        task_v_a, task_v_b, task_scene, task_filename, _task_worker, task_eval_mode = task
        if task_eval_mode != eval_mode:
            raise ConflictError("评测模式已变化，请重新进入评测")
        if (
            (v_a, v_b) != (task_v_a, task_v_b)
            or vote.scene != task_scene
            or vote.filename != task_filename
        ):
            raise ConflictError("提交内容与当前任务不一致")
        _ensure_result_mode_exclusive(
            cursor, task_type, task_v_a, task_v_b, task_scene, user_id, eval_mode
        )
        _complete_owned_task(cursor, vote.task_id, user_id, eval_mode)
        cursor.execute(
            """
            INSERT INTO results_log (
                task_id, eval_mode, task_type, v_a, v_b, scene, filename, overall, aesthetic, logic, consistency, fidelity,
                worker, timestamp, duration_seconds, user_id,
                bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vote.task_id,
                eval_mode,
                task_type,
                task_v_a,
                task_v_b,
                task_scene,
                task_filename,
                overall,
                dim_values["aesthetic"],
                dim_values["logic"],
                dim_values["consistency"],
                dim_values["fidelity"],
                worker,
                now_beijing_iso(),
                vote.duration_seconds,
                user_id,
                json.dumps(tags_a, ensure_ascii=False),
                json.dumps(tags_b, ensure_ascii=False),
                json.dumps(categories_from_tags(tags_a), ensure_ascii=False),
                json.dumps(categories_from_tags(tags_b), ensure_ascii=False),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"status": "ok"}


def skip_task(
    task_id: int,
    task_type: str,
    user_id: int,
    eval_mode: str = "full",
    worker: str = "",
) -> dict:
    task_type = normalize_task_type(task_type)
    eval_mode = normalize_eval_mode(eval_mode)
    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        task = _get_owned_working_task(cursor, task_id, task_type, user_id)
        if task[5] != eval_mode:
            raise ConflictError("评测模式已变化，请重新进入评测")
        authenticated_worker = worker or task[4]
        _ensure_result_mode_exclusive(
            cursor, task_type, task[0], task[1], task[2], user_id, eval_mode
        )
        _complete_owned_task(cursor, task_id, user_id, eval_mode)
        cursor.execute(
            """
            INSERT INTO results_log (
                task_id, eval_mode, task_type, v_a, v_b, scene, filename, overall, aesthetic, logic, consistency, fidelity,
                worker, timestamp, skipped, user_id,
                bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'skipped', 'skipped', 'skipped', 'skipped', 'skipped', ?, ?, 1, ?, '[]', '[]', '[]', '[]')
            """,
            (
                task_id,
                eval_mode,
                task_type,
                task[0],
                task[1],
                task[2],
                task[3],
                authenticated_worker,
                now_beijing_iso(),
                user_id,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"status": "ok"}
