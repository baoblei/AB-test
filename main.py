import csv
import json
import os
import random
import shutil
import sqlite3
import zipfile
from datetime import datetime, timedelta
from io import StringIO
from typing import Dict, List, Optional

import bcrypt
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from pydantic import BaseModel

app = FastAPI(title="MLLM Multi-Dim Eval Professional")

RESULT_DIR = "results"
PROMPT_DIR = "prompt"
REF_IMAGE_DIR = "ref_images"
DB_PATH = "database.db"
SECRET_KEY = "ab_test_secret_key_2024_secure"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

for path in (RESULT_DIR, PROMPT_DIR, REF_IMAGE_DIR):
    os.makedirs(path, exist_ok=True)

app.mount("/images", StaticFiles(directory=RESULT_DIR), name="images")
app.mount("/ref-images", StaticFiles(directory=REF_IMAGE_DIR), name="ref_images")

TASK_CONFIGS: Dict[str, Dict[str, object]] = {
    "T2I": {
        "result_root": os.path.join(RESULT_DIR, "T2I"),
        "prompt_root": os.path.join(PROMPT_DIR, "T2I"),
        "ref_root": os.path.join(REF_IMAGE_DIR, "T2I"),
        "eval_dims": ["aesthetic", "logic", "consistency"],
        "dashboard_dims": ["overall", "aesthetic", "logic", "consistency"],
        "bad_case_options": {
            "美学缺陷": ["乱码", "色彩异常", "明显噪点", "网格伪影", "模糊失焦"],
            "结构畸变": ["物体粘连", "透视问题", "空间扭曲"],
            "人像": ["人脸扭曲", "肢体畸变"],
            "语义问题": ["语义丢失", "对象错误"],
            "文本错误": ["文字乱码", "文字缺失", "额外文字"],
            "安全违规": ["涉黄", "暴力", "侵权风险"],
        },
        "show_ref": False,
        "upload_has_ref": False,
    },
    "TI2I": {
        "result_root": os.path.join(RESULT_DIR, "TI2I"),
        "prompt_root": os.path.join(PROMPT_DIR, "TI2I"),
        "ref_root": os.path.join(REF_IMAGE_DIR, "TI2I"),
        "eval_dims": ["aesthetic", "logic", "consistency", "fidelity"],
        "dashboard_dims": ["overall", "aesthetic", "logic", "consistency", "fidelity"],
        "bad_case_options": {
            "美学缺陷": ["乱码", "色彩异常", "明显噪点", "网格伪影", "模糊失焦"],
            "结构畸变": ["物体粘连", "透视问题", "空间扭曲"],
            "人像": ["人脸扭曲", "肢体畸变"],
            "语义问题": ["语义丢失", "对象错误"],
            "文本错误": ["文字乱码", "文字缺失", "额外文字"],
            "保真": ["过度编辑", "属性污染", "保真度差"],
            "安全违规": ["涉黄", "暴力", "侵权风险"],
        },
        "show_ref": True,
        "upload_has_ref": True,
    },
}

DIM_LABELS = {
    "overall": "整体",
    "aesthetic": "美学",
    "logic": "合理性",
    "consistency": "一致性",
    "fidelity": "保真度",
}

BAD_CASE_LABEL_TO_CATEGORY = {
    label: category
    for config in TASK_CONFIGS.values()
    for category, labels in config["bad_case_options"].items()
    for label in labels
}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_task_config(task_type: str) -> dict:
    if task_type not in TASK_CONFIGS:
        raise HTTPException(status_code=400, detail="无效任务类型")
    return TASK_CONFIGS[task_type]


def ensure_column(cursor, table_name: str, column_name: str, definition: str):
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing = {row[1] for row in cursor.fetchall()}
    if column_name not in existing:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT UNIQUE,
            role TEXT DEFAULT 'evaluator',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            ip_address TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS results_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT DEFAULT 'T2I',
            v_a TEXT,
            v_b TEXT,
            scene TEXT,
            filename TEXT,
            overall TEXT,
            aesthetic TEXT,
            logic TEXT,
            consistency TEXT,
            fidelity TEXT,
            worker TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            duration_seconds INTEGER,
            skipped INTEGER DEFAULT 0,
            user_id INTEGER,
            bad_case_tags_a TEXT DEFAULT '[]',
            bad_case_tags_b TEXT DEFAULT '[]',
            bad_case_categories_a TEXT DEFAULT '[]',
            bad_case_categories_b TEXT DEFAULT '[]'
        )
        """
    )
    ensure_column(cursor, "results_log", "task_type", "TEXT DEFAULT 'T2I'")
    ensure_column(cursor, "results_log", "fidelity", "TEXT DEFAULT 'tie'")
    ensure_column(cursor, "results_log", "bad_case_tags_a", "TEXT DEFAULT '[]'")
    ensure_column(cursor, "results_log", "bad_case_tags_b", "TEXT DEFAULT '[]'")
    ensure_column(cursor, "results_log", "bad_case_categories_a", "TEXT DEFAULT '[]'")
    ensure_column(cursor, "results_log", "bad_case_categories_b", "TEXT DEFAULT '[]'")

    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pair_tasks'")
    row = cursor.fetchone()
    if row and "task_type" not in (row[0] or ""):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pair_tasks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT DEFAULT 'T2I',
                v_a TEXT,
                v_b TEXT,
                scene TEXT,
                filename TEXT,
                status TEXT DEFAULT 'pending',
                worker TEXT,
                assigned_user_id INTEGER,
                UNIQUE(task_type, v_a, v_b, scene, filename, worker)
            )
            """
        )
        cursor.execute(
            """
            INSERT OR IGNORE INTO pair_tasks_new
            (id, task_type, v_a, v_b, scene, filename, status, worker, assigned_user_id)
            SELECT id, 'T2I', v_a, v_b, scene, filename, status, worker, assigned_user_id
            FROM pair_tasks
            """
        )
        cursor.execute("DROP TABLE pair_tasks")
        cursor.execute("ALTER TABLE pair_tasks_new RENAME TO pair_tasks")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pair_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT DEFAULT 'T2I',
            v_a TEXT,
            v_b TEXT,
            scene TEXT,
            filename TEXT,
            status TEXT DEFAULT 'pending',
            worker TEXT,
            assigned_user_id INTEGER,
            UNIQUE(task_type, v_a, v_b, scene, filename, worker)
        )
        """
    )
    ensure_column(cursor, "pair_tasks", "task_type", "TEXT DEFAULT 'T2I'")

    cursor.execute("SELECT id FROM users WHERE username='admin'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, email) VALUES (?, ?, ?, ?)",
            ("admin", hash_password("admin123"), "admin", "admin@example.com"),
        )

    conn.commit()
    conn.close()


def normalize_task_type(task_type: str) -> str:
    return task_type.upper()


def get_result_root(task_type: str) -> str:
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    preferred = config["result_root"]
    if os.path.isdir(preferred):
        return preferred
    if task_type == "T2I":
        return RESULT_DIR
    return preferred


def get_prompt_root(task_type: str) -> str:
    config = get_task_config(normalize_task_type(task_type))
    preferred = config["prompt_root"]
    if os.path.isdir(preferred):
        return preferred
    return PROMPT_DIR


def get_ref_root(task_type: str) -> str:
    config = get_task_config(normalize_task_type(task_type))
    preferred = config["ref_root"]
    if os.path.isdir(preferred):
        return preferred
    return REF_IMAGE_DIR


def get_versions_for_type(task_type: str) -> List[str]:
    root = get_result_root(task_type)
    if not os.path.isdir(root):
        return []
    return sorted([name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name))])


def get_scene_path(task_type: str, version: str, scene: str) -> str:
    return os.path.join(get_result_root(task_type), version, scene)


def get_common_scenes(task_type: str, v1: str, v2: str) -> List[str]:
    p1 = os.path.join(get_result_root(task_type), v1)
    p2 = os.path.join(get_result_root(task_type), v2)
    if not (os.path.isdir(p1) and os.path.isdir(p2)):
        return []
    s1 = {d for d in os.listdir(p1) if os.path.isdir(os.path.join(p1, d))}
    s2 = {d for d in os.listdir(p2) if os.path.isdir(os.path.join(p2, d))}
    return sorted(list(s1 & s2))


def list_scene_files(task_type: str, version: str, scene: str) -> List[str]:
    scene_path = get_scene_path(task_type, version, scene)
    if not os.path.isdir(scene_path):
        return []
    return sorted([f for f in os.listdir(scene_path) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))])


def get_prompt_text(task_type: str, scene: str, filename: str) -> str:
    prompt_root = get_prompt_root(task_type)
    candidates = [os.path.join(prompt_root, f"{scene}.txt"), os.path.join(PROMPT_DIR, f"{scene}.txt")]
    image_id = os.path.splitext(filename)[0]
    for prompt_file in candidates:
        if not os.path.exists(prompt_file):
            continue
        with open(prompt_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 2 and parts[0] == image_id:
                    return parts[1]
    return "Prompt content not found."


def get_ref_image_url(task_type: str, scene: str, filename: str) -> Optional[str]:
    ref_root = get_ref_root(task_type)
    direct_path = os.path.join(ref_root, scene, filename)
    if os.path.exists(direct_path):
        rel = os.path.relpath(direct_path, REF_IMAGE_DIR).replace(os.sep, "/")
        return f"/ref-images/{rel}"
    fallback = os.path.join(REF_IMAGE_DIR, scene, filename)
    if os.path.exists(fallback):
        rel = os.path.relpath(fallback, REF_IMAGE_DIR).replace(os.sep, "/")
        return f"/ref-images/{rel}"
    return None


def log_operation(user_id: int, action: str, details: str, ip_address: str = ""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO operation_logs (user_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
        (user_id, action, details, ip_address),
    )
    conn.commit()
    conn.close()


def normalize_bad_case_tags(tags: Optional[List[str]]) -> List[str]:
    if not tags:
        return []
    result = []
    for tag in tags:
        if tag in BAD_CASE_LABEL_TO_CATEGORY and tag not in result:
            result.append(tag)
    return result


def categories_from_tags(tags: List[str]) -> List[str]:
    categories = []
    for tag in tags:
        category = BAD_CASE_LABEL_TO_CATEGORY.get(tag)
        if category and category not in categories:
            categories.append(category)
    return categories


def safe_load_json_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def derive_overall_result(dim_results: List[str]) -> str:
    counts = {}
    for result in dim_results:
        counts[result] = counts.get(result, 0) + 1
    if not counts:
        return "tie"
    best_choice = max(counts.items(), key=lambda item: item[1])[0]
    top_count = counts[best_choice]
    if top_count == 1:
        return "tie"
    if sum(1 for count in counts.values() if count == top_count) > 1:
        return "tie"
    return best_choice


def build_bad_case_stats(rows):
    stats = {
        "v_a": {"bad_count": 0, "total": 0, "rate": 0.0, "categories": {}, "tags": {}},
        "v_b": {"bad_count": 0, "total": 0, "rate": 0.0, "categories": {}, "tags": {}},
    }
    for row in rows:
        tags_a = safe_load_json_list(row["bad_case_tags_a"])
        tags_b = safe_load_json_list(row["bad_case_tags_b"])
        stats["v_a"]["total"] += 1
        stats["v_b"]["total"] += 1
        if tags_a:
            stats["v_a"]["bad_count"] += 1
        if tags_b:
            stats["v_b"]["bad_count"] += 1
        for side_key, tags in (("v_a", tags_a), ("v_b", tags_b)):
            seen_categories = set()
            for tag in tags:
                category = BAD_CASE_LABEL_TO_CATEGORY.get(tag)
                if not category:
                    continue
                stats[side_key]["tags"][tag] = stats[side_key]["tags"].get(tag, 0) + 1
                if category not in seen_categories:
                    stats[side_key]["categories"][category] = stats[side_key]["categories"].get(category, 0) + 1
                    seen_categories.add(category)
    for key in ("v_a", "v_b"):
        total = stats[key]["total"]
        stats[key]["rate"] = round(stats[key]["bad_count"] / total * 100, 1) if total else 0.0
    return stats


async def get_current_user(request: Request, access_token: Optional[str] = Cookie(None)) -> Optional[dict]:
    if not access_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            access_token = auth_header[7:]
        else:
            return None
    payload = decode_token(access_token)
    if not payload or not payload.get("sub"):
        return None
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role, email FROM users WHERE id=? AND is_active=1", (payload["sub"],))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "username": row[1], "role": row[2], "email": row[3]}


async def require_login(user: dict = Depends(get_current_user)) -> dict:
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


class UserRegister(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


class VoteSubmit(BaseModel):
    task_type: str
    task_id: int
    v_left: str
    v_right: str
    scene: str
    filename: str
    worker: str
    aesthetic: str
    logic: str
    consistency: str
    fidelity: Optional[str] = None
    bad_case_left: Optional[List[str]] = None
    bad_case_right: Optional[List[str]] = None
    duration_seconds: Optional[int] = None


@app.on_event("startup")
def startup():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE pair_tasks SET status='pending', worker=NULL WHERE status='working'")
    conn.commit()
    conn.close()


@app.post("/api/auth/register")
def register(user: UserRegister, request: Request):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username=?", (user.username,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="用户名已存在")
    if user.email:
        cursor.execute("SELECT id FROM users WHERE email=?", (user.email,))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="邮箱已被注册")
    cursor.execute(
        "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
        (user.username, hash_password(user.password), user.email),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    log_operation(user_id, "register", f"新用户注册: {user.username}", request.client.host)
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(user: UserLogin, request: Request):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, password_hash, role FROM users WHERE username=? AND is_active=1", (user.username,))
    row = cursor.fetchone()
    if not row or not verify_password(user.password, row[1]):
        conn.close()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    cursor.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (row[0],))
    conn.commit()
    conn.close()
    access_token = create_access_token({"sub": str(row[0]), "role": row[2]})
    log_operation(row[0], "login", f"用户登录: {user.username}", request.client.host)
    response = JSONResponse({"status": "ok", "role": row[2]})
    response.set_cookie(key="access_token", value=access_token, httponly=True, max_age=86400)
    return response


@app.post("/api/auth/logout")
def logout(user: dict = Depends(require_login)):
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(key="access_token")
    return response


@app.get("/api/auth/me")
def get_me(user: dict = Depends(require_login)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, role, created_at, last_login FROM users WHERE id=?",
        (user["id"],),
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


@app.put("/api/auth/password")
def change_password(data: PasswordChange, user: dict = Depends(require_login)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],))
    row = cursor.fetchone()
    if not row or not verify_password(data.old_password, row[0]):
        conn.close()
        raise HTTPException(status_code=400, detail="旧密码错误")
    cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(data.new_password), user["id"]))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/api/task_types")
def get_task_types():
    return [
        {
            "key": key,
            "label": key,
            "show_ref": config["show_ref"],
            "dims": config["eval_dims"],
        }
        for key, config in TASK_CONFIGS.items()
    ]


@app.get("/api/task_config")
def api_task_config(task_type: str):
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    return {
        "task_type": task_type,
        "show_ref": config["show_ref"],
        "eval_dims": [{"key": dim, "label": DIM_LABELS[dim]} for dim in config["eval_dims"]],
        "dashboard_dims": [{"key": dim, "label": DIM_LABELS[dim]} for dim in config["dashboard_dims"]],
        "bad_case_options": config["bad_case_options"],
    }


@app.get("/api/versions")
def get_versions(task_type: str):
    return get_versions_for_type(normalize_task_type(task_type))


@app.get("/api/scenes")
def get_scenes(task_type: str, v1: str, v2: str):
    return get_common_scenes(normalize_task_type(task_type), v1, v2)


@app.get("/api/get_prompt")
def get_prompt(task_type: str, scene: str, filename: str):
    return get_prompt_text(normalize_task_type(task_type), scene, filename)


def ensure_pair_tasks(task_type: str, worker: str, v_a: str, v_b: str, scene: str, user_id: int):
    conn = sqlite3.connect(DB_PATH)
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


@app.get("/api/get_task")
def get_task(task_type: str, worker: str, v1: str, v2: str, scene: str, user: dict = Depends(require_login)):
    task_type = normalize_task_type(task_type)
    get_task_config(task_type)
    v_a, v_b = sorted([v1, v2])
    ensure_pair_tasks(task_type, worker, v_a, v_b, scene, user["id"])
    conn = sqlite3.connect(DB_PATH)
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
    conn.close()
    if not row:
        return {"status": "finished"}

    display = [v_a, v_b]
    random.shuffle(display)
    filename = row[1]
    payload = {
        "task_type": task_type,
        "task_id": row[0],
        "scene": scene,
        "filename": filename,
        "prompt": get_prompt_text(task_type, scene, filename),
        "left_img": f"/images/{task_type}/{display[0]}/{scene}/{filename}" if os.path.isdir(os.path.join(RESULT_DIR, task_type)) else f"/images/{display[0]}/{scene}/{filename}",
        "right_img": f"/images/{task_type}/{display[1]}/{scene}/{filename}" if os.path.isdir(os.path.join(RESULT_DIR, task_type)) else f"/images/{display[1]}/{scene}/{filename}",
        "v_left": display[0],
        "v_right": display[1],
        "show_ref": bool(get_task_config(task_type)["show_ref"]),
        "ref_img": get_ref_image_url(task_type, scene, filename),
    }
    return payload


@app.get("/api/progress")
def get_progress(task_type: str, worker: str, v1: str, v2: str, scene: str, user: dict = Depends(require_login)):
    task_type = normalize_task_type(task_type)
    v_a, v_b = sorted([v1, v2])
    conn = sqlite3.connect(DB_PATH)
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
        WHERE task_type=? AND v_a=? AND v_b=? AND scene=? AND worker=? AND skipped=1
        """,
        (task_type, v_a, v_b, scene, worker),
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


@app.post("/api/submit")
def submit_vote(vote: VoteSubmit, user: dict = Depends(require_login)):
    task_type = normalize_task_type(vote.task_type)
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

    dim_values = {
        "aesthetic": resolve(vote.aesthetic),
        "logic": resolve(vote.logic),
        "consistency": resolve(vote.consistency),
        "fidelity": resolve(vote.fidelity) if "fidelity" in config["eval_dims"] else "tie",
    }
    overall = derive_overall_result([dim_values[dim] for dim in config["eval_dims"]])
    v_a, v_b = sorted([vote.v_left, vote.v_right])

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO results_log (
            task_type, v_a, v_b, scene, filename, overall, aesthetic, logic, consistency, fidelity,
            worker, duration_seconds, user_id,
            bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
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
            vote.duration_seconds,
            user["id"],
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


@app.post("/api/skip_task")
def skip_task(task_id: int, task_type: str, user: dict = Depends(require_login)):
    task_type = normalize_task_type(task_type)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT v_a, v_b, scene, filename, worker FROM pair_tasks WHERE id=? AND task_type=?",
        (task_id, task_type),
    )
    task = cursor.fetchone()
    if not task:
        conn.close()
        raise HTTPException(status_code=404, detail="任务不存在")
    cursor.execute(
        """
        INSERT INTO results_log (
            task_type, v_a, v_b, scene, filename, overall, aesthetic, logic, consistency, fidelity,
            worker, skipped, user_id,
            bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
        )
        VALUES (?, ?, ?, ?, ?, 'skipped', 'skipped', 'skipped', 'skipped', 'skipped', ?, 1, ?, '[]', '[]', '[]', '[]')
        """,
        (task_type, task[0], task[1], task[2], task[3], task[4], user["id"]),
    )
    cursor.execute("UPDATE pair_tasks SET status='completed' WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/api/my_history")
def get_my_history(user: dict = Depends(require_login)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT task_type, v_a, v_b, scene, filename, overall, aesthetic, logic, consistency, fidelity, timestamp, duration_seconds, skipped
        FROM results_log WHERE user_id=? ORDER BY timestamp DESC LIMIT 100
        """,
        (user["id"],),
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


@app.get("/api/my_stats")
def get_my_stats(user: dict = Depends(require_login)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM results_log WHERE user_id=? AND skipped=0", (user["id"],))
    total = cursor.fetchone()[0]
    cursor.execute("SELECT AVG(duration_seconds) FROM results_log WHERE user_id=? AND duration_seconds IS NOT NULL", (user["id"],))
    avg_duration = cursor.fetchone()[0] or 0
    cursor.execute(
        "SELECT scene, COUNT(*) FROM results_log WHERE user_id=? AND skipped=0 GROUP BY scene",
        (user["id"],),
    )
    scene_stats = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return {"total_evaluations": total, "avg_duration_seconds": round(avg_duration, 1), "scene_stats": scene_stats}


def fetch_result_rows(task_type: str, v_a: Optional[str] = None, v_b: Optional[str] = None, scene: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    query = "SELECT * FROM results_log WHERE task_type=? AND skipped=0"
    params: List[object] = [task_type]
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


def aggregate_pair_rows(task_type: str) -> List[dict]:
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
            pair_data["dims"][dim] = {
                "v_a_wins": sum(1 for row in pair_rows if row[dim] == v_a),
                "v_b_wins": sum(1 for row in pair_rows if row[dim] == v_b),
                "tie_count": sum(1 for row in pair_rows if row[dim] == "tie"),
            }
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
                scene_data["dims"][dim] = {
                    "v_a_wins": sum(1 for row in scene_rows if row[dim] == v_a),
                    "v_b_wins": sum(1 for row in scene_rows if row[dim] == v_b),
                    "tie_count": sum(1 for row in scene_rows if row[dim] == "tie"),
                }
            pair_data["scenes"].append(scene_data)
        result.append(pair_data)
    return result


@app.get("/api/dashboard_overview")
def dashboard_overview(task_type: str):
    task_type = normalize_task_type(task_type)
    return {
        "task_type": task_type,
        "dims": [{"key": dim, "label": DIM_LABELS[dim]} for dim in get_task_config(task_type)["dashboard_dims"]],
        "pairs": aggregate_pair_rows(task_type),
    }


@app.get("/api/worker_stats")
def worker_stats(task_type: str, v1: str, v2: str, scene: Optional[str] = None):
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
            entry[dim] = {
                "v_a_wins": sum(1 for row in worker_rows if row[dim] == v_a),
                "v_b_wins": sum(1 for row in worker_rows if row[dim] == v_b),
                "tie_count": sum(1 for row in worker_rows if row[dim] == "tie"),
            }
        result.append(entry)
    return result


@app.get("/api/detail_results")
def detail_results(task_type: str, v1: str, v2: str, scene: str):
    task_type = normalize_task_type(task_type)
    v_a, v_b = sorted([v1, v2])
    rows = fetch_result_rows(task_type, v_a, v_b, scene)
    rows = sorted(rows, key=lambda row: (row["worker"], row["filename"], row["timestamp"]), reverse=True)
    return [
        {
            "task_type": task_type,
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
            "prompt": get_prompt_text(task_type, row["scene"], row["filename"]),
            "ref_img": get_ref_image_url(task_type, row["scene"], row["filename"]),
            "bad_case_tags_a": safe_load_json_list(row["bad_case_tags_a"]),
            "bad_case_tags_b": safe_load_json_list(row["bad_case_tags_b"]),
        }
        for row in rows
    ]


@app.get("/api/bad_case_details")
def bad_case_details(
    task_type: str,
    v1: str,
    v2: str,
    scene: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
):
    task_type = normalize_task_type(task_type)
    v_a, v_b = sorted([v1, v2])
    rows = fetch_result_rows(task_type, v_a, v_b, scene)
    results = []
    for row in sorted(rows, key=lambda item: item["timestamp"], reverse=True):
        prompt = get_prompt_text(task_type, row["scene"], row["filename"])
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


@app.get("/api/export")
def export_data(format: str = "json", task_type: str = "T2I", v1: Optional[str] = None, v2: Optional[str] = None, scene: Optional[str] = None):
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
    conn = sqlite3.connect(DB_PATH)
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


@app.get("/api/ranking")
def ranking(task_type: str = "T2I", scene: Optional[str] = None, dimension: str = "overall"):
    task_type = normalize_task_type(task_type)
    if dimension not in TASK_CONFIGS[task_type]["dashboard_dims"]:
        raise HTTPException(status_code=400, detail="无效维度")
    rows = fetch_result_rows(task_type, scene=scene)
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
            {"model": model_name, "wins": entry["wins"], "total": total, "win_rate": round(entry["wins"] / total * 100, 1) if total else 0}
        )
    ranking_rows.sort(key=lambda item: item["win_rate"], reverse=True)
    return ranking_rows


@app.get("/api/admin/users")
def get_users(admin: dict = Depends(require_admin)):
    conn = sqlite3.connect(DB_PATH)
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


@app.put("/api/admin/users/{user_id}")
def update_user_status(user_id: int, is_active: int, admin: dict = Depends(require_admin)):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET is_active=? WHERE id=?", (is_active, user_id))
    conn.commit()
    conn.close()
    log_operation(admin["id"], "admin_action", f"更新用户 {user_id} 状态为 {is_active}")
    return {"status": "ok"}


@app.get("/api/admin/stats")
def admin_stats(admin: dict = Depends(require_admin)):
    conn = sqlite3.connect(DB_PATH)
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


@app.get("/api/admin/logs")
def admin_logs(limit: int = 100, admin: dict = Depends(require_admin)):
    conn = sqlite3.connect(DB_PATH)
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


def save_uploaded_zip(target_path: str, upload_file: UploadFile):
    if os.path.exists(target_path):
        shutil.rmtree(target_path)
    os.makedirs(target_path, exist_ok=True)
    temp_zip = f"temp_{datetime.utcnow().timestamp():.0f}_{upload_file.filename}"
    with open(temp_zip, "wb") as f:
        shutil.copyfileobj(upload_file.file, f)
    try:
        with zipfile.ZipFile(temp_zip, "r") as zf:
            zf.extractall(target_path)
        items = [item for item in os.listdir(target_path) if not item.startswith(".") and item != "__MACOSX"]
        if len(items) == 1 and os.path.isdir(os.path.join(target_path, items[0])):
            inner = os.path.join(target_path, items[0])
            for name in os.listdir(inner):
                shutil.move(os.path.join(inner, name), target_path)
            os.rmdir(inner)
    finally:
        if os.path.exists(temp_zip):
            os.remove(temp_zip)


@app.post("/api/upload")
async def upload_data(task_type: str = Form(...), version: str = Form(...), scene: str = Form(...), file: UploadFile = File(...)):
    task_type = normalize_task_type(task_type)
    save_uploaded_zip(os.path.join(get_result_root(task_type), version, scene), file)
    return {"message": "Success"}


@app.post("/api/upload_ref")
async def upload_ref(task_type: str = Form(...), scene: str = Form(...), file: UploadFile = File(...)):
    task_type = normalize_task_type(task_type)
    save_uploaded_zip(os.path.join(get_ref_root(task_type), scene), file)
    return {"message": "Success"}


@app.get("/", response_class=HTMLResponse)
async def index():
    return open("templates/index.html", encoding="utf-8").read()


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return open("templates/login.html", encoding="utf-8").read()


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return open("templates/dashboard.html", encoding="utf-8").read()


@app.get("/profile", response_class=HTMLResponse)
async def profile():
    return open("templates/profile.html", encoding="utf-8").read()


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return open("templates/admin.html", encoding="utf-8").read()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
