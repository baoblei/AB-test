import sqlite3

from .config import DB_PATH


def connect(row_factory: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn


def ensure_column(cursor: sqlite3.Cursor, table_name: str, column_name: str, definition: str):
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing = {row[1] for row in cursor.fetchall()}
    if column_name not in existing:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db():
    conn = connect()
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
            eval_mode TEXT DEFAULT 'full',
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
    ensure_column(cursor, "results_log", "eval_mode", "TEXT DEFAULT 'full'")
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
        from .passwords import hash_password

        cursor.execute(
            "INSERT INTO users (username, password_hash, role, email) VALUES (?, ?, ?, ?)",
            ("admin", hash_password("admin123"), "admin", "admin@example.com"),
        )

    conn.commit()
    conn.close()


def reset_working_tasks():
    conn = connect()
    conn.execute("UPDATE pair_tasks SET status='pending', worker=NULL WHERE status='working'")
    conn.commit()
    conn.close()


def log_operation(user_id: int, action: str, details: str, ip_address: str = ""):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO operation_logs (user_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
        (user_id, action, details, ip_address),
    )
    conn.commit()
    conn.close()
