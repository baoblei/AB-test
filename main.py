import os
import random
import sqlite3
import shutil
import zipfile
import time
import json
import bcrypt
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request, Cookie
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from jose import JWTError, jwt

app = FastAPI(title="MLLM Multi-Dim Eval Professional")

# --- 配置区 ---
RESULT_DIR = "results"
PROMPT_DIR = "prompt"
DB_PATH = "database.db"
SECRET_KEY = "ab_test_secret_key_2024_secure"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

os.makedirs(RESULT_DIR, exist_ok=True)
os.makedirs(PROMPT_DIR, exist_ok=True)

app.mount("/images", StaticFiles(directory=RESULT_DIR), name="images")
templates = Jinja2Templates(directory="templates")

BAD_CASE_LABELS = {
    "美学缺陷": ["乱码", "色彩异常", "明显噪点", "网格伪影", "模糊失焦"],
    "结构畸变": ["物体粘连", "透视问题", "空间扭曲"],
    "人像": ["人脸扭曲", "肢体畸变"],
    "语义问题": ["语义丢失", "对象错误"],
    "安全违规": ["涉黄", "暴力", "侵权风险"],
}
BAD_CASE_LABEL_TO_CATEGORY = {
    label: category
    for category, labels in BAD_CASE_LABELS.items()
    for label in labels
}

# --- 密码工具函数 ---
def hash_password(password: str) -> str:
    """使用 bcrypt 加密密码"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

# --- JWT 工具函数 ---
def create_access_token(data: dict) -> str:
    """创建 JWT token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[dict]:
    """解码 JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

# --- 数据库初始化 ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 用户表
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        email TEXT UNIQUE,
        role TEXT DEFAULT 'evaluator',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_login DATETIME,
        is_active INTEGER DEFAULT 1
    )''')

    # 操作日志表
    cursor.execute('''CREATE TABLE IF NOT EXISTS operation_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT,
        details TEXT,
        ip_address TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    # 评测记录表 (扩展字段)
    cursor.execute('''CREATE TABLE IF NOT EXISTS results_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        v_a TEXT, v_b TEXT, scene TEXT, filename TEXT,
        overall TEXT, aesthetic TEXT, logic TEXT, consistency TEXT,
        worker TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        duration_seconds INTEGER,
        skipped INTEGER DEFAULT 0,
        user_id INTEGER
    )''')
    ensure_column(cursor, "results_log", "bad_case_tags_a", "TEXT DEFAULT '[]'")
    ensure_column(cursor, "results_log", "bad_case_tags_b", "TEXT DEFAULT '[]'")
    ensure_column(cursor, "results_log", "bad_case_categories_a", "TEXT DEFAULT '[]'")
    ensure_column(cursor, "results_log", "bad_case_categories_b", "TEXT DEFAULT '[]'")

    # 任务分配表
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pair_tasks'")
    row = cursor.fetchone()
    if row and "UNIQUE(v_a, v_b, scene, filename)" in row[0]:
        cursor.execute("CREATE TABLE IF NOT EXISTS pair_tasks_new ("
                       "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                       "v_a TEXT, v_b TEXT, scene TEXT, filename TEXT,"
                       "status TEXT DEFAULT 'pending',"
                       "worker TEXT,"
                       "assigned_user_id INTEGER,"
                       "UNIQUE(v_a, v_b, scene, filename, worker))")
        cursor.execute("INSERT OR IGNORE INTO pair_tasks_new "
                       "(id, v_a, v_b, scene, filename, status, worker) "
                       "SELECT id, v_a, v_b, scene, filename, status, worker FROM pair_tasks")
        cursor.execute("DROP TABLE pair_tasks")
        cursor.execute("ALTER TABLE pair_tasks_new RENAME TO pair_tasks")
        conn.commit()

    cursor.execute('''CREATE TABLE IF NOT EXISTS pair_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        v_a TEXT, v_b TEXT, scene TEXT, filename TEXT,
        status TEXT DEFAULT 'pending',
        worker TEXT,
        assigned_user_id INTEGER,
        UNIQUE(v_a, v_b, scene, filename, worker)
    )''')

    # 创建默认管理员账户
    cursor.execute("SELECT id FROM users WHERE username='admin'")
    if not cursor.fetchone():
        admin_hash = hash_password("admin123")
        cursor.execute("INSERT INTO users (username, password_hash, role, email) VALUES (?, ?, ?, ?)",
                      ("admin", admin_hash, "admin", "admin@example.com"))

    conn.commit()
    conn.close()

# --- 认证依赖 ---
async def get_current_user(request: Request, access_token: Optional[str] = Cookie(None)) -> Optional[dict]:
    """获取当前登录用户"""
    if not access_token:
        # 尝试从 header 获取
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            access_token = auth_header[7:]
        else:
            return None

    payload = decode_token(access_token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role, email FROM users WHERE id=? AND is_active=1", (user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return None

    return {"id": user[0], "username": user[1], "role": user[2], "email": user[3]}

async def require_login(user: dict = Depends(get_current_user)) -> dict:
    """要求用户登录"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user

async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """要求管理员权限"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user

# --- 数据模型 ---
class UserRegister(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str

class VoteSubmit(BaseModel):
    task_id: int
    v_left: str
    v_right: str
    scene: str
    filename: str
    worker: str
    overall: Optional[str] = None
    aesthetic: str
    logic: str
    consistency: str
    bad_case_left: Optional[List[str]] = None
    bad_case_right: Optional[List[str]] = None
    duration_seconds: Optional[int] = None

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

# --- 辅助函数 ---
def get_prompt_text(scene: str, filename: str) -> str:
    prompt_file = os.path.join(PROMPT_DIR, f"{scene}.txt")
    if not os.path.exists(prompt_file):
        return "Prompt file not found."
    img_id = os.path.splitext(filename)[0]
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 2 and parts[0] == img_id:
                    return parts[1]
    except Exception as e:
        print(f"Error reading prompt: {e}")
    return "Prompt content not found."

def log_operation(user_id: int, action: str, details: str, ip_address: str = ""):
    """记录操作日志"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO operation_logs (user_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
        (user_id, action, details, ip_address)
    )
    conn.commit()
    conn.close()

def ensure_column(cursor, table_name: str, column_name: str, definition: str):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {row[1] for row in cursor.fetchall()}
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

def normalize_bad_case_tags(tags: Optional[List[str]]) -> List[str]:
    if not tags:
        return []
    unique_tags = []
    for tag in tags:
        if tag in BAD_CASE_LABEL_TO_CATEGORY and tag not in unique_tags:
            unique_tags.append(tag)
    return unique_tags

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

def derive_overall_result(aesthetic: str, logic: str, consistency: str) -> str:
    choices = [aesthetic, logic, consistency]
    counts = {}
    for choice in choices:
        counts[choice] = counts.get(choice, 0) + 1
    best_choice = max(counts.items(), key=lambda item: item[1])[0]
    top_count = counts[best_choice]
    if top_count == 1:
        return "tie"
    if sum(1 for count in counts.values() if count == top_count) > 1:
        return "tie"
    return best_choice

# --- 启动事件 ---
@app.on_event("startup")
def startup():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE pair_tasks SET status='pending', worker=NULL WHERE status='working'")
    conn.commit()
    conn.close()

# ========== 用户认证 API ==========

@app.post("/api/auth/register")
def register(user: UserRegister, request: Request):
    """用户注册"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 检查用户名是否已存在
    cursor.execute("SELECT id FROM users WHERE username=?", (user.username,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 检查邮箱是否已存在
    if user.email:
        cursor.execute("SELECT id FROM users WHERE email=?", (user.email,))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="邮箱已被注册")

    # 创建用户
    password_hash = hash_password(user.password)
    cursor.execute(
        "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
        (user.username, password_hash, user.email)
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    # 记录日志
    log_operation(user_id, "register", f"新用户注册: {user.username}", request.client.host)

    return {"status": "ok", "message": "注册成功"}

@app.post("/api/auth/login")
def login(user: UserLogin, request: Request):
    """用户登录"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, password_hash, role FROM users WHERE username=? AND is_active=1", (user.username,))
    result = cursor.fetchone()

    if not result or not verify_password(user.password, result[1]):
        conn.close()
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user_id, _, role = result

    # 更新最后登录时间
    cursor.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

    # 创建 token
    access_token = create_access_token({"sub": str(user_id), "role": role})

    # 记录日志
    log_operation(user_id, "login", f"用户登录: {user.username}", request.client.host)

    response = JSONResponse({"status": "ok", "role": role})
    response.set_cookie(key="access_token", value=access_token, httponly=True, max_age=86400)
    return response

@app.post("/api/auth/logout")
def logout(user: dict = Depends(require_login)):
    """用户登出"""
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(key="access_token")
    return response

@app.get("/api/auth/me")
def get_me(user: dict = Depends(require_login)):
    """获取当前用户信息"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, role, created_at, last_login FROM users WHERE id=?",
        (user["id"],)
    )
    result = cursor.fetchone()
    conn.close()

    if not result:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {
        "id": result[0],
        "username": result[1],
        "email": result[2],
        "role": result[3],
        "created_at": result[4],
        "last_login": result[5]
    }

@app.put("/api/auth/password")
def change_password(data: PasswordChange, user: dict = Depends(require_login)):
    """修改密码"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 验证旧密码
    cursor.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],))
    result = cursor.fetchone()
    if not result or not verify_password(data.old_password, result[0]):
        conn.close()
        raise HTTPException(status_code=400, detail="旧密码错误")

    # 更新密码
    new_hash = hash_password(data.new_password)
    cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user["id"]))
    conn.commit()
    conn.close()

    return {"status": "ok", "message": "密码修改成功"}

# ========== 评测功能 API ==========

@app.get("/api/versions")
def get_versions():
    return sorted([d for d in os.listdir(RESULT_DIR) if os.path.isdir(os.path.join(RESULT_DIR, d))])

@app.get("/api/scenes")
def get_scenes(v1: str, v2: str):
    p1 = os.path.join(RESULT_DIR, v1)
    p2 = os.path.join(RESULT_DIR, v2)
    if not (os.path.exists(p1) and os.path.exists(p2)): return []
    s1 = set([d for d in os.listdir(p1) if os.path.isdir(os.path.join(p1, d))])
    s2 = set([d for d in os.listdir(p2) if os.path.isdir(os.path.join(p2, d))])
    return sorted(list(s1 & s2))

@app.get("/api/get_task")
def get_task(worker: str, v1: str, v2: str, scene: str, user: dict = Depends(require_login)):
    v_a, v_b = sorted([v1, v2])
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 优先获取该用户未完成的"断点"任务
    cursor.execute("""
        SELECT id, filename FROM pair_tasks
        WHERE v_a=? AND v_b=? AND scene=? AND status='working' AND worker=?
        LIMIT 1
    """, (v_a, v_b, scene, worker))
    task = cursor.fetchone()

    if not task:
        # 2. 如果没有，检查是否需要为该用户初始化该场景任务到DB
        scene_path = os.path.join(RESULT_DIR, v_a, scene)
        if os.path.exists(scene_path):
            files = [f for f in os.listdir(scene_path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            for f in files:
                cursor.execute(
                    "INSERT OR IGNORE INTO pair_tasks (v_a, v_b, scene, filename, worker, assigned_user_id) VALUES (?,?,?,?,?,?)",
                    (v_a, v_b, scene, f, worker, user["id"]))
            conn.commit()

        # 3. 随机抢占该用户的一个 pending 任务
        cursor.execute("BEGIN EXCLUSIVE TRANSACTION")
        cursor.execute(
            "SELECT id, filename FROM pair_tasks WHERE v_a=? AND v_b=? AND scene=? AND status='pending' AND worker=?",
            (v_a, v_b, scene, worker))
        pending = cursor.fetchall()
        task = random.choice(pending) if pending else None
        if task:
            cursor.execute("UPDATE pair_tasks SET status='working' WHERE id=?", (task[0],))
            conn.commit()

    conn.close()
    if not task: return {"status": "finished"}

    t_id, fname = task
    display = [v_a, v_b]
    random.shuffle(display)

    return {
        "task_id": t_id, "scene": scene, "filename": fname,
        "prompt": get_prompt_text(scene, fname),
        "left_img": f"/images/{display[0]}/{scene}/{fname}",
        "right_img": f"/images/{display[1]}/{scene}/{fname}",
        "v_left": display[0], "v_right": display[1]
    }

@app.get("/api/progress")
def get_progress(worker: str, v1: str, v2: str, scene: str, user: dict = Depends(require_login)):
    """获取评测进度"""
    v_a, v_b = sorted([v1, v2])
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 获取总数
    cursor.execute("""
        SELECT COUNT(*) FROM pair_tasks
        WHERE v_a=? AND v_b=? AND scene=? AND worker=?
    """, (v_a, v_b, scene, worker))
    total = cursor.fetchone()[0]

    # 获取已完成数
    cursor.execute("""
        SELECT COUNT(*) FROM pair_tasks
        WHERE v_a=? AND v_b=? AND scene=? AND worker=? AND status='completed'
    """, (v_a, v_b, scene, worker))
    completed = cursor.fetchone()[0]

    # 获取跳过数
    cursor.execute("""
        SELECT COUNT(*) FROM results_log
        WHERE v_a=? AND v_b=? AND scene=? AND worker=? AND skipped=1
    """, (v_a, v_b, scene, worker))
    skipped = cursor.fetchone()[0]

    conn.close()

    return {
        "total": total,
        "completed": completed,
        "skipped": skipped,
        "remaining": total - completed - skipped,
        "percent": round((completed + skipped) / total * 100, 1) if total > 0 else 0
    }

@app.post("/api/submit")
def submit_vote(vote: VoteSubmit, user: dict = Depends(require_login)):
    def get_real_val(choice):
        if choice == 'left': return vote.v_left
        if choice == 'right': return vote.v_right
        return 'tie'

    left_tags = normalize_bad_case_tags(vote.bad_case_left)
    right_tags = normalize_bad_case_tags(vote.bad_case_right)

    if vote.v_left == vote.v_right:
        raise HTTPException(status_code=400, detail="左右模型不能相同")

    if vote.v_left < vote.v_right:
        tags_a, tags_b = left_tags, right_tags
    else:
        tags_a, tags_b = right_tags, left_tags

    categories_a = categories_from_tags(tags_a)
    categories_b = categories_from_tags(tags_b)

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        v_a, v_b = sorted([vote.v_left, vote.v_right])
        aesthetic_val = get_real_val(vote.aesthetic)
        logic_val = get_real_val(vote.logic)
        consistency_val = get_real_val(vote.consistency)
        overall_val = get_real_val(vote.overall) if vote.overall else derive_overall_result(
            aesthetic_val, logic_val, consistency_val
        )
        cursor.execute("""
            INSERT INTO results_log (
                v_a, v_b, scene, filename, overall, aesthetic, logic, consistency,
                worker, duration_seconds, user_id,
                bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (v_a, v_b, vote.scene, vote.filename,
              overall_val, aesthetic_val, logic_val, consistency_val,
              vote.worker, vote.duration_seconds, user["id"],
              json.dumps(tags_a, ensure_ascii=False), json.dumps(tags_b, ensure_ascii=False),
              json.dumps(categories_a, ensure_ascii=False), json.dumps(categories_b, ensure_ascii=False)))

        cursor.execute("UPDATE pair_tasks SET status='completed' WHERE id=?", (vote.task_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}

@app.post("/api/skip_task")
def skip_task(task_id: int, user: dict = Depends(require_login)):
    """跳过任务"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 获取任务信息
    cursor.execute("SELECT v_a, v_b, scene, filename, worker FROM pair_tasks WHERE id=?", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        raise HTTPException(status_code=404, detail="任务不存在")

    v_a, v_b, scene, filename, worker = task

    # 记录跳过
    cursor.execute("""
        INSERT INTO results_log (
            v_a, v_b, scene, filename, overall, aesthetic, logic, consistency,
            worker, skipped, user_id,
            bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        v_a, v_b, scene, filename, 'skipped', 'skipped', 'skipped', 'skipped',
        worker, 1, user["id"], '[]', '[]', '[]', '[]'
    ))

    cursor.execute("UPDATE pair_tasks SET status='completed' WHERE id=?", (task_id,))
    conn.commit()
    conn.close()

    return {"status": "ok"}

@app.get("/api/my_history")
def get_my_history(user: dict = Depends(require_login)):
    """获取个人评测历史"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v_a, v_b, scene, filename, overall, aesthetic, logic, consistency, timestamp, duration_seconds, skipped
        FROM results_log WHERE user_id=? ORDER BY timestamp DESC LIMIT 100
    """, (user["id"],))
    rows = cursor.fetchall()
    conn.close()

    return [{
        "v_a": r[0], "v_b": r[1], "scene": r[2], "filename": r[3],
        "overall": r[4], "aesthetic": r[5], "logic": r[6], "consistency": r[7],
        "timestamp": r[8], "duration_seconds": r[9], "skipped": r[10]
    } for r in rows]

@app.get("/api/my_stats")
def get_my_stats(user: dict = Depends(require_login)):
    """获取个人统计数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 总评测数
    cursor.execute("SELECT COUNT(*) FROM results_log WHERE user_id=? AND skipped=0", (user["id"],))
    total = cursor.fetchone()[0]

    # 平均耗时
    cursor.execute("SELECT AVG(duration_seconds) FROM results_log WHERE user_id=? AND duration_seconds IS NOT NULL", (user["id"],))
    avg_duration = cursor.fetchone()[0] or 0

    # 按场景统计
    cursor.execute("""
        SELECT scene, COUNT(*) FROM results_log
        WHERE user_id=? AND skipped=0 GROUP BY scene
    """, (user["id"],))
    scene_stats = {r[0]: r[1] for r in cursor.fetchall()}

    conn.close()

    return {
        "total_evaluations": total,
        "avg_duration_seconds": round(avg_duration, 1),
        "scene_stats": scene_stats
    }

def build_bad_case_stats(rows):
    stats = {
        "v_a": {"bad_count": 0, "total": 0, "rate": 0, "categories": {}, "tags": {}},
        "v_b": {"bad_count": 0, "total": 0, "rate": 0, "categories": {}, "tags": {}},
    }
    for _, _, _, _, tags_a_raw, tags_b_raw, _, _ in rows:
        tags_a = safe_load_json_list(tags_a_raw)
        tags_b = safe_load_json_list(tags_b_raw)

        stats["v_a"]["total"] += 1
        stats["v_b"]["total"] += 1

        if tags_a:
            stats["v_a"]["bad_count"] += 1
        if tags_b:
            stats["v_b"]["bad_count"] += 1

        for side_key, tags in (("v_a", tags_a), ("v_b", tags_b)):
            side_stats = stats[side_key]
            seen_categories = set()
            for tag in tags:
                category = BAD_CASE_LABEL_TO_CATEGORY.get(tag)
                if not category:
                    continue
                side_stats["tags"][tag] = side_stats["tags"].get(tag, 0) + 1
                if category not in seen_categories:
                    side_stats["categories"][category] = side_stats["categories"].get(category, 0) + 1
                    seen_categories.add(category)

    for side_key in ("v_a", "v_b"):
        side_stats = stats[side_key]
        total = side_stats["total"] or 0
        side_stats["rate"] = round(side_stats["bad_count"] / total * 100, 1) if total else 0
    return stats

# ========== 看板功能 API ==========

@app.get("/api/dashboard")
def get_dashboard():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v_a, v_b, scene,
               SUM(CASE WHEN overall = v_a THEN 1 ELSE 0 END) as v_a_wins,
               SUM(CASE WHEN overall = v_b THEN 1 ELSE 0 END) as v_b_wins,
               COUNT(*) as total
        FROM results_log WHERE skipped=0 GROUP BY v_a, v_b, scene
    """)
    rows = cursor.fetchall()
    conn.close()
    return [{"pair": f"{r[0]} vs {r[1]}", "scene": r[2], "v_a_wins": r[3], "v_b_wins": r[4], "total": r[5]} for r in rows]

@app.get("/api/dashboard_v2")
def get_dashboard_v2():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v_a, v_b, scene,
               SUM(CASE WHEN overall = v_a THEN 1 ELSE 0 END) as o_a,
               SUM(CASE WHEN overall = v_b THEN 1 ELSE 0 END) as o_b,
               SUM(CASE WHEN aesthetic = v_a THEN 1 ELSE 0 END) as a_a,
               SUM(CASE WHEN aesthetic = v_b THEN 1 ELSE 0 END) as a_b,
               SUM(CASE WHEN logic = v_a THEN 1 ELSE 0 END) as l_a,
               SUM(CASE WHEN logic = v_b THEN 1 ELSE 0 END) as l_b,
               SUM(CASE WHEN consistency = v_a THEN 1 ELSE 0 END) as c_a,
               SUM(CASE WHEN consistency = v_b THEN 1 ELSE 0 END) as c_b,
               COUNT(*) as total
        FROM results_log WHERE skipped=0 GROUP BY v_a, v_b, scene
    """)
    rows = cursor.fetchall()
    conn.close()

    res = []
    for r in rows:
        res.append({
            "pair": f"{r[0]} vs {r[1]}",
            "scene": r[2],
            "total": r[11],
            "dims": {
                "overall": {"v_a_wins": r[3], "v_b_wins": r[4]},
                "aesthetic": {"v_a_wins": r[5], "v_b_wins": r[6]},
                "logic": {"v_a_wins": r[7], "v_b_wins": r[8]},
                "consistency": {"v_a_wins": r[9], "v_b_wins": r[10]},
            }
        })
    return res

@app.get("/api/dashboard_v3")
def get_dashboard_v3():
    """按 AB 版本对分组的综合统计（跨所有场景汇总）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 按版本对分组汇总
    cursor.execute("""
        SELECT v_a, v_b,
               SUM(CASE WHEN overall = v_a THEN 1 ELSE 0 END) as o_a,
               SUM(CASE WHEN overall = v_b THEN 1 ELSE 0 END) as o_b,
               SUM(CASE WHEN aesthetic = v_a THEN 1 ELSE 0 END) as a_a,
               SUM(CASE WHEN aesthetic = v_b THEN 1 ELSE 0 END) as a_b,
               SUM(CASE WHEN logic = v_a THEN 1 ELSE 0 END) as l_a,
               SUM(CASE WHEN logic = v_b THEN 1 ELSE 0 END) as l_b,
               SUM(CASE WHEN consistency = v_a THEN 1 ELSE 0 END) as c_a,
               SUM(CASE WHEN consistency = v_b THEN 1 ELSE 0 END) as c_b,
               COUNT(*) as total
        FROM results_log WHERE skipped=0 GROUP BY v_a, v_b
    """)
    pair_rows = cursor.fetchall()

    # 获取每个版本对下的场景明细
    result = []
    for r in pair_rows:
        v_a, v_b = r[0], r[1]

        cursor.execute("""
            SELECT scene, filename, worker, timestamp, bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
            FROM results_log
            WHERE v_a=? AND v_b=? AND skipped=0
        """, (v_a, v_b))
        pair_bad_case_rows = cursor.fetchall()
        pair_bad_case_stats = build_bad_case_stats(pair_bad_case_rows)

        # 获取该版本对下所有场景的统计（使用参数绑定）
        cursor.execute("""
            SELECT scene,
                   SUM(CASE WHEN overall = ? THEN 1 ELSE 0 END) as o_a,
                   SUM(CASE WHEN overall = ? THEN 1 ELSE 0 END) as o_b,
                   SUM(CASE WHEN aesthetic = ? THEN 1 ELSE 0 END) as a_a,
                   SUM(CASE WHEN aesthetic = ? THEN 1 ELSE 0 END) as a_b,
                   SUM(CASE WHEN logic = ? THEN 1 ELSE 0 END) as l_a,
                   SUM(CASE WHEN logic = ? THEN 1 ELSE 0 END) as l_b,
                   SUM(CASE WHEN consistency = ? THEN 1 ELSE 0 END) as c_a,
                   SUM(CASE WHEN consistency = ? THEN 1 ELSE 0 END) as c_b,
                   COUNT(*) as total
            FROM results_log WHERE v_a=? AND v_b=? AND skipped=0 GROUP BY scene
        """, (v_a, v_b, v_a, v_b, v_a, v_b, v_a, v_b, v_a, v_b))
        scene_rows = cursor.fetchall()

        scenes = []
        for sr in scene_rows:
            scene_name = sr[0]
            scene_bad_case_rows = [row for row in pair_bad_case_rows if row[0] == scene_name]
            scenes.append({
                "scene": scene_name,
                "total": sr[9],
                "dims": {
                    "overall": {"v_a_wins": sr[1], "v_b_wins": sr[2]},
                    "aesthetic": {"v_a_wins": sr[3], "v_b_wins": sr[4]},
                    "logic": {"v_a_wins": sr[5], "v_b_wins": sr[6]},
                    "consistency": {"v_a_wins": sr[7], "v_b_wins": sr[8]},
                },
                "bad_case": build_bad_case_stats(scene_bad_case_rows)
            })

        result.append({
            "pair": f"{v_a} vs {v_b}",
            "v_a": v_a,
            "v_b": v_b,
            "total": r[10],
            "dims": {
                "overall": {"v_a_wins": r[2], "v_b_wins": r[3]},
                "aesthetic": {"v_a_wins": r[4], "v_b_wins": r[5]},
                "logic": {"v_a_wins": r[6], "v_b_wins": r[7]},
                "consistency": {"v_a_wins": r[8], "v_b_wins": r[9]},
            },
            "bad_case": pair_bad_case_stats,
            "scenes": scenes
        })

    conn.close()
    return result

@app.get("/api/worker_stats")
def get_worker_stats(v1: str, v2: str, scene: Optional[str] = None):
    v_a, v_b = sorted([v1, v2])
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if scene:
        cursor.execute("""
            SELECT worker,
                   COUNT(*) as total,
                   SUM(CASE WHEN overall = ? THEN 1 ELSE 0 END) as o_a,
                   SUM(CASE WHEN overall = ? THEN 1 ELSE 0 END) as o_b,
                   SUM(CASE WHEN aesthetic = ? THEN 1 ELSE 0 END) as a_a,
                   SUM(CASE WHEN aesthetic = ? THEN 1 ELSE 0 END) as a_b,
                   SUM(CASE WHEN logic = ? THEN 1 ELSE 0 END) as l_a,
                   SUM(CASE WHEN logic = ? THEN 1 ELSE 0 END) as l_b,
                   SUM(CASE WHEN consistency = ? THEN 1 ELSE 0 END) as c_a,
                   SUM(CASE WHEN consistency = ? THEN 1 ELSE 0 END) as c_b
            FROM results_log
            WHERE v_a=? AND v_b=? AND scene=? AND skipped=0
            GROUP BY worker
            ORDER BY worker
        """, (v_a, v_b, v_a, v_b, v_a, v_b, v_a, v_b, v_a, v_b, scene))
    else:
        # 不指定场景时，获取所有场景的汇总
        cursor.execute("""
            SELECT worker,
                   COUNT(*) as total,
                   SUM(CASE WHEN overall = ? THEN 1 ELSE 0 END) as o_a,
                   SUM(CASE WHEN overall = ? THEN 1 ELSE 0 END) as o_b,
                   SUM(CASE WHEN aesthetic = ? THEN 1 ELSE 0 END) as a_a,
                   SUM(CASE WHEN aesthetic = ? THEN 1 ELSE 0 END) as a_b,
                   SUM(CASE WHEN logic = ? THEN 1 ELSE 0 END) as l_a,
                   SUM(CASE WHEN logic = ? THEN 1 ELSE 0 END) as l_b,
                   SUM(CASE WHEN consistency = ? THEN 1 ELSE 0 END) as c_a,
                   SUM(CASE WHEN consistency = ? THEN 1 ELSE 0 END) as c_b
            FROM results_log
            WHERE v_a=? AND v_b=? AND skipped=0
            GROUP BY worker
            ORDER BY worker
        """, (v_a, v_b, v_a, v_b, v_a, v_b, v_a, v_b, v_a, v_b))

    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        total = r[1] or 0
        result.append({
            "worker": r[0],
            "total": total,
            "overall": {"v_a_wins": r[2], "v_b_wins": r[3]},
            "aesthetic": {"v_a_wins": r[4], "v_b_wins": r[5]},
            "logic": {"v_a_wins": r[6], "v_b_wins": r[7]},
            "consistency": {"v_a_wins": r[8], "v_b_wins": r[9]},
        })
    return result

@app.get("/api/detail_results")
def get_detail_results(v1: str, v2: str, scene: str):
    v_a, v_b = sorted([v1, v2])
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT filename, overall, aesthetic, logic, consistency, worker, timestamp, duration_seconds,
               bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
        FROM results_log WHERE v_a=? AND v_b=? AND scene=? AND skipped=0 ORDER BY worker, filename, timestamp DESC
    """, (v_a, v_b, scene))
    rows = cursor.fetchall()
    conn.close()
    return [{
        "filename": r[0], "overall": r[1], "aesthetic": r[2],
        "logic": r[3], "consistency": r[4], "worker": r[5], "time": r[6], "duration": r[7],
        "bad_case_tags_a": safe_load_json_list(r[8]),
        "bad_case_tags_b": safe_load_json_list(r[9]),
        "bad_case_categories_a": safe_load_json_list(r[10]),
        "bad_case_categories_b": safe_load_json_list(r[11]),
    } for r in rows]

@app.get("/api/bad_case_details")
def get_bad_case_details(
    v1: str,
    v2: str,
    scene: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
):
    v_a, v_b = sorted([v1, v2])
    if model and model not in {v_a, v_b}:
        raise HTTPException(status_code=400, detail="模型参数无效")
    if category and category not in BAD_CASE_LABELS:
        raise HTTPException(status_code=400, detail="坏例类别无效")
    if tag and tag not in BAD_CASE_LABEL_TO_CATEGORY:
        raise HTTPException(status_code=400, detail="坏例标签无效")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    query = """
        SELECT scene, filename, worker, timestamp, duration_seconds,
               bad_case_tags_a, bad_case_tags_b, bad_case_categories_a, bad_case_categories_b
        FROM results_log
        WHERE v_a=? AND v_b=? AND skipped=0
    """
    params = [v_a, v_b]
    if scene:
        query += " AND scene=?"
        params.append(scene)
    query += " ORDER BY timestamp DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        row_scene, filename, worker, timestamp, duration_seconds, tags_a_raw, tags_b_raw, categories_a_raw, categories_b_raw = row
        side_payloads = [
            {
                "model": v_a,
                "tags": safe_load_json_list(tags_a_raw),
                "categories": safe_load_json_list(categories_a_raw),
            },
            {
                "model": v_b,
                "tags": safe_load_json_list(tags_b_raw),
                "categories": safe_load_json_list(categories_b_raw),
            },
        ]
        for payload in side_payloads:
            if not payload["tags"]:
                continue
            if model and payload["model"] != model:
                continue
            if category and category not in payload["categories"]:
                continue
            if tag and tag not in payload["tags"]:
                continue
            results.append({
                "scene": row_scene,
                "filename": filename,
                "worker": worker,
                "time": timestamp,
                "duration": duration_seconds,
                "model": payload["model"],
                "categories": payload["categories"],
                "tags": payload["tags"],
            })
    return {
        "filters": {"scene": scene, "model": model, "category": category, "tag": tag},
        "results": results
    }

@app.get("/api/export")
def export_data(format: str = "json", v1: Optional[str] = None, v2: Optional[str] = None,
                scene: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """导出数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = "SELECT * FROM results_log WHERE skipped=0"
    params = []

    if v1 and v2:
        v_a, v_b = sorted([v1, v2])
        query += " AND v_a=? AND v_b=?"
        params.extend([v_a, v_b])
    if scene:
        query += " AND scene=?"
        params.append(scene)
    if start_date:
        query += " AND timestamp >= ?"
        params.append(start_date)
    if end_date:
        query += " AND timestamp <= ?"
        params.append(end_date + " 23:59:59")

    cursor.execute(query, params)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    conn.close()

    if format == "csv":
        import csv
        from io import StringIO
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        writer.writerows(rows)
        return {"data": output.getvalue(), "format": "csv"}
    else:
        return {"data": [dict(zip(columns, row)) for row in rows], "format": "json"}

@app.get("/api/ranking")
def get_ranking(scene: Optional[str] = None, dimension: str = "overall"):
    """模型排行榜"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 获取所有对战数据
    query = "SELECT v_a, v_b, overall, aesthetic, logic, consistency FROM results_log WHERE skipped=0"
    params = []
    if scene:
        query += " AND scene=?"
        params.append(scene)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    # 统计每个模型的胜场
    model_wins = {}
    model_totals = {}

    for r in rows:
        v_a, v_b = r[0], r[1]
        dim_val = r[["overall", "aesthetic", "logic", "consistency"].index(dimension) + 2]

        # 初始化
        for v in [v_a, v_b]:
            if v not in model_wins:
                model_wins[v] = 0
                model_totals[v] = 0

        model_totals[v_a] += 1
        model_totals[v_b] += 1

        if dim_val == v_a:
            model_wins[v_a] += 1
        elif dim_val == v_b:
            model_wins[v_b] += 1

    # 计算胜率
    ranking = []
    for model in model_wins:
        total = model_totals[model]
        wins = model_wins[model]
        win_rate = wins / total if total > 0 else 0
        ranking.append({"model": model, "wins": wins, "total": total, "win_rate": round(win_rate * 100, 1)})

    ranking.sort(key=lambda x: x["win_rate"], reverse=True)
    return ranking

@app.get("/api/trend")
def get_trend(v1: str, v2: str, scene: str, days: int = 30):
    """胜率趋势数据"""
    v_a, v_b = sorted([v1, v2])
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 按日期统计
    cursor.execute("""
        SELECT DATE(timestamp) as date,
               SUM(CASE WHEN overall = ? THEN 1 ELSE 0 END) as a_wins,
               SUM(CASE WHEN overall = ? THEN 1 ELSE 0 END) as b_wins,
               COUNT(*) as total
        FROM results_log
        WHERE v_a=? AND v_b=? AND scene=? AND skipped=0
        AND timestamp >= DATE('now', ?)
        GROUP BY DATE(timestamp)
        ORDER BY date
    """, (v_a, v_b, v_a, v_b, scene, f'-{days} days'))
    rows = cursor.fetchall()
    conn.close()

    return [{
        "date": r[0],
        "a_win_rate": round(r[1] / r[3] * 100, 1) if r[3] > 0 else 0,
        "b_win_rate": round(r[2] / r[3] * 100, 1) if r[3] > 0 else 0,
        "total": r[3]
    } for r in rows]

# ========== 管理员 API ==========

@app.get("/api/admin/users")
def get_users(admin: dict = Depends(require_admin)):
    """获取用户列表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, role, created_at, last_login, is_active
        FROM users ORDER BY created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    return [{
        "id": r[0], "username": r[1], "email": r[2], "role": r[3],
        "created_at": r[4], "last_login": r[5], "is_active": r[6]
    } for r in rows]

@app.put("/api/admin/users/{user_id}")
def update_user_status(user_id: int, is_active: int, admin: dict = Depends(require_admin)):
    """更新用户状态"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active=? WHERE id=?", (is_active, user_id))
    conn.commit()
    conn.close()

    log_operation(admin["id"], "admin_action", f"更新用户 {user_id} 状态为 {is_active}")
    return {"status": "ok"}

@app.get("/api/admin/stats")
def get_admin_stats(admin: dict = Depends(require_admin)):
    """系统统计总览"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 用户数
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]

    # 评测数
    cursor.execute("SELECT COUNT(*) FROM results_log WHERE skipped=0")
    eval_count = cursor.fetchone()[0]

    # 今日评测数
    cursor.execute("SELECT COUNT(*) FROM results_log WHERE skipped=0 AND DATE(timestamp)=DATE('now')")
    today_eval = cursor.fetchone()[0]

    # 模型数
    cursor.execute("SELECT COUNT(DISTINCT v_a) FROM results_log")
    model_count = cursor.fetchone()[0] * 2  # 粗略估计

    conn.close()

    return {
        "user_count": user_count,
        "eval_count": eval_count,
        "today_eval": today_eval,
        "model_count": model_count
    }

@app.get("/api/admin/logs")
def get_logs(limit: int = 100, admin: dict = Depends(require_admin)):
    """获取操作日志"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT l.id, u.username, l.action, l.details, l.ip_address, l.timestamp
        FROM operation_logs l LEFT JOIN users u ON l.user_id=u.id
        ORDER BY l.timestamp DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()

    return [{
        "id": r[0], "username": r[1] or "系统", "action": r[2],
        "details": r[3], "ip": r[4], "timestamp": r[5]
    } for r in rows]

# ========== 上传功能 ==========

@app.post("/api/upload")
async def upload_data(version: str = Form(...), scene: str = Form(...), file: UploadFile = File(...)):
    target_path = os.path.join(RESULT_DIR, version, scene)
    if os.path.exists(target_path): shutil.rmtree(target_path)
    os.makedirs(target_path, exist_ok=True)

    temp_zip = f"temp_{version}_{scene}.zip"
    with open(temp_zip, "wb") as f: shutil.copyfileobj(file.file, f)

    try:
        with zipfile.ZipFile(temp_zip, 'r') as z:
            z.extractall(target_path)

        items = [i for i in os.listdir(target_path) if not i.startswith('.') and i != "__MACOSX"]
        if len(items) == 1 and os.path.isdir(os.path.join(target_path, items[0])):
            sub = os.path.join(target_path, items[0])
            for f in os.listdir(sub): shutil.move(os.path.join(sub, f), target_path)
            os.rmdir(sub)
    finally:
        if os.path.exists(temp_zip): os.remove(temp_zip)
    return {"message": "Success"}

@app.get("/api/get_prompt")
def get_prompt(scene: str, filename: str):
    return get_prompt_text(scene, filename)

# ========== 页面路由 ==========

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
