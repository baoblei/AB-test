import os
from typing import Dict

from .errors import InvalidTaskTypeError


RESULT_DIR = "results"
PROMPT_DIR = "prompt"
REF_IMAGE_DIR = "ref_images"
DB_PATH = "database.db"
SECRET_KEY = "ab_test_secret_key_2024_secure"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

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
            "人像肢体": ["人脸扭曲", "肢体畸变"],
            "语义问题": ["关键对象缺失", "关键对象错误"],
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
            "人像肢体": ["人脸扭曲", "肢体畸变"],
            "语义问题": ["关键对象缺失", "关键对象错误"],
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


def ensure_data_dirs():
    for path in (RESULT_DIR, PROMPT_DIR, REF_IMAGE_DIR):
        os.makedirs(path, exist_ok=True)


def normalize_task_type(task_type: str) -> str:
    return (task_type or "").upper()


def get_task_config(task_type: str) -> dict:
    normalized = normalize_task_type(task_type)
    if normalized not in TASK_CONFIGS:
        raise InvalidTaskTypeError("无效任务类型")
    return TASK_CONFIGS[normalized]


def dim_payload(dims: list[str]) -> list[dict]:
    return [{"key": dim, "label": DIM_LABELS[dim]} for dim in dims]
