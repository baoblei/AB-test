from .database import connect, log_operation


def get_users() -> list[dict]:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, role, created_at, last_login, is_active FROM users ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "username": row[1],
            "email": row[2],
            "role": row[3],
            "created_at": row[4],
            "last_login": row[5],
            "is_active": row[6],
        }
        for row in rows
    ]


def update_user_status(user_id: int, is_active: int, admin_id: int) -> dict:
    conn = connect()
    conn.execute("UPDATE users SET is_active=? WHERE id=?", (is_active, user_id))
    conn.commit()
    conn.close()
    log_operation(admin_id, "admin_action", f"更新用户 {user_id} 状态为 {is_active}")
    return {"status": "ok"}


def admin_stats() -> dict:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM results_log WHERE skipped=0")
    eval_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM results_log WHERE skipped=0 AND DATE(timestamp)=DATE('now')")
    today_eval = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT v_a) + COUNT(DISTINCT v_b) FROM results_log")
    model_count = cursor.fetchone()[0]
    conn.close()
    return {"user_count": user_count, "eval_count": eval_count, "today_eval": today_eval, "model_count": model_count}


def admin_logs(limit: int = 100) -> list[dict]:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT l.id, u.username, l.action, l.details, l.ip_address, l.timestamp
        FROM operation_logs l LEFT JOIN users u ON l.user_id=u.id
        ORDER BY l.timestamp DESC LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {"id": row[0], "username": row[1] or "系统", "action": row[2], "details": row[3], "ip": row[4], "timestamp": row[5]}
        for row in rows
    ]
