import os
import random
import sqlite3
import shutil
import zipfile
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="MLLM Multi-Dim Eval Professional")

# --- 配置区 ---
RESULT_DIR = "results"
PROMPT_DIR = "prompt"
DB_PATH = "database.db"
os.makedirs(RESULT_DIR, exist_ok=True)
os.makedirs(PROMPT_DIR, exist_ok=True)

app.mount("/images", StaticFiles(directory=RESULT_DIR), name="images")

# --- 数据库初始化 ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pair_tasks'")
    row = cursor.fetchone()
    if row and "UNIQUE(v_a, v_b, scene, filename)" in row[0]:
        cursor.execute("CREATE TABLE IF NOT EXISTS pair_tasks_new ("
                       "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                       "v_a TEXT, v_b TEXT, scene TEXT, filename TEXT,"
                       "status TEXT DEFAULT 'pending',"
                       "worker TEXT,"
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
        UNIQUE(v_a, v_b, scene, filename, worker)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS results_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        v_a TEXT, v_b TEXT, scene TEXT, filename TEXT,
        overall TEXT, aesthetic TEXT, logic TEXT, consistency TEXT,
        worker TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE pair_tasks SET status='pending', worker=NULL WHERE status='working'")
    conn.commit()
    conn.close()

def get_prompt_text(scene: str, filename: str):
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

class VoteSubmit(BaseModel):
    task_id: int
    v_left: str
    v_right: str
    scene: str
    filename: str
    worker: str
    overall: str
    aesthetic: str
    logic: str
    consistency: str

# --- API ---

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
def get_task(worker: str, v1: str, v2: str, scene: str):
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
                    "INSERT OR IGNORE INTO pair_tasks (v_a, v_b, scene, filename, worker) VALUES (?,?,?,?,?)",
                    (v_a, v_b, scene, f, worker))
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

@app.post("/api/submit")
def submit_vote(vote: VoteSubmit):
    def get_real_val(choice):
        if choice == 'left': return vote.v_left
        if choice == 'right': return vote.v_right
        return 'tie'

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        v_a, v_b = sorted([vote.v_left, vote.v_right])
        cursor.execute("""
            INSERT INTO results_log (v_a, v_b, scene, filename, overall, aesthetic, logic, consistency, worker) 
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (v_a, v_b, vote.scene, vote.filename, 
              get_real_val(vote.overall), get_real_val(vote.aesthetic), 
              get_real_val(vote.logic), get_real_val(vote.consistency), vote.worker))
        
        cursor.execute("UPDATE pair_tasks SET status='completed' WHERE id=?", (vote.task_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}

@app.get("/api/dashboard")
def get_dashboard():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v_a, v_b, scene,
               SUM(CASE WHEN overall = v_a THEN 1 ELSE 0 END) as v_a_wins,
               SUM(CASE WHEN overall = v_b THEN 1 ELSE 0 END) as v_b_wins,
               COUNT(*) as total
        FROM results_log GROUP BY v_a, v_b, scene
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
        FROM results_log GROUP BY v_a, v_b, scene
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

@app.get("/api/worker_stats")
def get_worker_stats(v1: str, v2: str, scene: str):
    v_a, v_b = sorted([v1, v2])
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
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
        WHERE v_a=? AND v_b=? AND scene=?
        GROUP BY worker
        ORDER BY worker
    """, (v_a, v_b, v_a, v_b, v_a, v_b, v_a, v_b, v_a, v_b, scene))
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
        SELECT filename, overall, aesthetic, logic, consistency, worker, timestamp 
        FROM results_log WHERE v_a=? AND v_b=? AND scene=? ORDER BY worker, filename, timestamp DESC
    """, (v_a, v_b, scene))
    rows = cursor.fetchall()
    conn.close()
    return [{
        "filename": r[0], "overall": r[1], "aesthetic": r[2], 
        "logic": r[3], "consistency": r[4], "worker": r[5], "time": r[6]
    } for r in rows]

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

@app.get("/", response_class=HTMLResponse)
async def index():
    return open("templates/index.html", encoding="utf-8").read()

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return open("templates/dashboard.html", encoding="utf-8").read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
