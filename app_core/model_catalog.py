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
