from . import storage
from .config import normalize_task_type
from .database import connect
from .errors import AppError
from .storage import validate_storage_component


def validate_model_component(value: str, label: str) -> str:
    normalized = validate_storage_component(value, label)
    if "_" in normalized:
        raise AppError(f"{label}不能包含下划线 _")
    return normalized


def compose_model_name(class_name: str, model_name: str, version: str) -> str:
    parts = (
        validate_model_component(class_name, "class"),
        validate_model_component(model_name, "model"),
        validate_model_component(version, "version"),
    )
    return "_".join(parts)


def parse_model_name(full_name: str) -> dict:
    parts = full_name.split("_")
    if len(parts) == 3 and all(parts):
        class_name, model_name, version = parts
        return {
            "class_name": class_name,
            "model_name": model_name,
            "version": version,
            "full_name": full_name,
        }
    return {
        "class_name": None,
        "model_name": None,
        "version": full_name,
        "full_name": full_name,
    }


def get_database_model_names(task_type: str) -> list[str]:
    task_type = normalize_task_type(task_type)
    conn = connect()
    try:
        names = set()
        for table in ("pair_tasks", "results_log"):
            rows = conn.execute(
                f"""
                SELECT v_a FROM {table} WHERE task_type=? AND v_a IS NOT NULL AND v_a<>''
                UNION
                SELECT v_b FROM {table} WHERE task_type=? AND v_b IS NOT NULL AND v_b<>''
                """,
                (task_type, task_type),
            ).fetchall()
            names.update(row[0] for row in rows)
        return sorted(names)
    finally:
        conn.close()


def get_model_catalog(task_type: str) -> dict:
    task_type = normalize_task_type(task_type)
    names = set(storage.get_filesystem_model_names(task_type))
    names.update(get_database_model_names(task_type))
    return {
        "task_type": task_type,
        "models": [parse_model_name(name) for name in sorted(names)],
    }
