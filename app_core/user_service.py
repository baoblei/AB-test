from .auth import create_access_token
from .database import connect, log_operation
from .errors import AppError, UnauthorizedError
from .passwords import hash_password, verify_password
from .schemas import PasswordChange, UserLogin, UserRegister
from .time_utils import now_beijing_iso


def register_user(user: UserRegister, ip_address: str = "") -> dict:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username=?", (user.username,))
    if cursor.fetchone():
        conn.close()
        raise AppError("用户名已存在")

    if user.email:
        cursor.execute("SELECT id FROM users WHERE email=?", (user.email,))
        if cursor.fetchone():
            conn.close()
            raise AppError("邮箱已被注册")

    cursor.execute(
        "INSERT INTO users (username, password_hash, email, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (user.username, hash_password(user.password), user.email, "evaluator", now_beijing_iso()),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    log_operation(user_id, "register", f"新用户注册: {user.username}", ip_address)
    return {"status": "ok"}


def login_user(user: UserLogin, ip_address: str = "") -> dict:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, password_hash, role FROM users WHERE username=? AND is_active=1", (user.username,))
    row = cursor.fetchone()
    if not row or not verify_password(user.password, row[1]):
        conn.close()
        raise UnauthorizedError("用户名或密码错误")

    cursor.execute("UPDATE users SET last_login=? WHERE id=?", (now_beijing_iso(), row[0]))
    conn.commit()
    conn.close()

    access_token = create_access_token({"sub": str(row[0]), "role": row[2]})
    log_operation(row[0], "login", f"用户登录: {user.username}", ip_address)
    return {"status": "ok", "role": row[2], "access_token": access_token}


def get_user_profile(user_id: int) -> dict:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, role, created_at, last_login FROM users WHERE id=?",
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "role": row[3],
        "created_at": row[4],
        "last_login": row[5],
    }


def change_user_password(data: PasswordChange, user_id: int) -> dict:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE id=?", (user_id,))
    row = cursor.fetchone()
    if not row or not verify_password(data.old_password, row[0]):
        conn.close()
        raise AppError("旧密码错误")

    cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(data.new_password), user_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}


def get_my_history(user_id: int) -> list[dict]:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT task_type, v_a, v_b, scene, filename, overall, aesthetic, logic, consistency, fidelity, timestamp, duration_seconds, skipped
        FROM results_log WHERE user_id=? ORDER BY timestamp DESC LIMIT 100
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "task_type": row[0],
            "v_a": row[1],
            "v_b": row[2],
            "scene": row[3],
            "filename": row[4],
            "overall": row[5],
            "aesthetic": row[6],
            "logic": row[7],
            "consistency": row[8],
            "fidelity": row[9],
            "timestamp": row[10],
            "duration_seconds": row[11],
            "skipped": row[12],
        }
        for row in rows
    ]


def get_my_stats(user_id: int) -> dict:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM results_log WHERE user_id=? AND skipped=0", (user_id,))
    total = cursor.fetchone()[0]
    cursor.execute("SELECT AVG(duration_seconds) FROM results_log WHERE user_id=? AND duration_seconds IS NOT NULL", (user_id,))
    avg_duration = cursor.fetchone()[0] or 0
    cursor.execute(
        "SELECT scene, COUNT(*) FROM results_log WHERE user_id=? AND skipped=0 GROUP BY scene",
        (user_id,),
    )
    scene_stats = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return {"total_evaluations": total, "avg_duration_seconds": round(avg_duration, 1), "scene_stats": scene_stats}
