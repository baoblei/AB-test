import sqlite3

from .config import DB_PATH
from .time_utils import is_canonical_beijing_iso, legacy_utc_to_beijing_iso, now_beijing_iso


TIME_MIGRATION_KEY = "beijing_time_v1"
BUSINESS_TIME_COLUMNS = {
    "users": ("created_at", "last_login"),
    "operation_logs": ("timestamp",),
    "results_log": ("timestamp",),
}


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


def migrate_business_times(conn: sqlite3.Connection) -> dict:
    conn.execute("CREATE TABLE IF NOT EXISTS app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if conn.execute("SELECT 1 FROM app_metadata WHERE key=?", (TIME_MIGRATION_KEY,)).fetchone():
        return {"updated": 0, "invalid": 0}

    updated = 0
    invalid = 0
    for table, columns in BUSINESS_TIME_COLUMNS.items():
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not table_exists:
            continue
        for column in columns:
            for row_id, value in conn.execute(
                f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL"
            ):
                converted = legacy_utc_to_beijing_iso(value)
                if converted == value:
                    if not is_canonical_beijing_iso(value):
                        invalid += 1
                    continue
                conn.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (converted, row_id))
                updated += 1
    conn.execute(
        "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
        (TIME_MIGRATION_KEY, now_beijing_iso()),
    )
    conn.commit()
    return {"updated": updated, "invalid": invalid}


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
            created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', '+8 hours') || '+08:00'),
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
            timestamp DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', '+8 hours') || '+08:00')
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
            timestamp DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', '+8 hours') || '+08:00'),
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
            "INSERT INTO users (username, password_hash, role, email, created_at) VALUES (?, ?, ?, ?, ?)",
            ("admin", hash_password("admin123"), "admin", "admin@example.com", now_beijing_iso()),
        )

    migration_result = migrate_business_times(conn)
    if migration_result["invalid"]:
        print(f"Beijing time migration left {migration_result['invalid']} invalid values unchanged.")

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
    timestamp = now_beijing_iso()
    cursor.execute(
        "INSERT INTO operation_logs (user_id, action, details, ip_address, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, action, details, ip_address, timestamp),
    )
    conn.commit()
    conn.close()
