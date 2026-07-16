import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app_core import config, storage
from app_core.dataset_download_service import create_dataset_artifact, list_datasets
from app_core.errors import AppError


class DatasetRoots:
    def __init__(self, root: Path):
        self.prompt_roots = {
            task_type: root / "prompt" / task_type for task_type in ("T2I", "TI2I")
        }
        self.ref_roots = {
            task_type: root / "ref_images" / task_type for task_type in ("T2I", "TI2I")
        }

    def write_prompt(self, task_type: str, scene: str, content: str) -> None:
        root = self.prompt_roots[task_type]
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{scene}.txt").write_text(content, encoding="utf-8")

    def write_ref(self, task_type: str, scene: str, filename: str, data: bytes = b"image") -> None:
        root = self.ref_roots[task_type] / scene
        root.mkdir(parents=True, exist_ok=True)
        (root / filename).write_bytes(data)


@contextmanager
def configured_dataset_roots():
    with tempfile.TemporaryDirectory() as temp_dir:
        roots = DatasetRoots(Path(temp_dir))
        task_configs = {
            **config.TASK_CONFIGS,
            **{
                task_type: {
                    **config.TASK_CONFIGS[task_type],
                    "prompt_root": str(roots.prompt_roots[task_type]),
                    "ref_root": str(roots.ref_roots[task_type]),
                }
                for task_type in ("T2I", "TI2I")
            },
        }
        for root in (*roots.prompt_roots.values(), *roots.ref_roots.values()):
            root.mkdir(parents=True, exist_ok=True)
        with (
            patch.object(config, "TASK_CONFIGS", task_configs),
            patch.object(storage, "PROMPT_DIR", str(Path(temp_dir) / "prompt")),
            patch.object(storage, "REF_IMAGE_DIR", str(Path(temp_dir) / "ref_images")),
        ):
            yield roots


class DatasetMetadataTests(unittest.TestCase):
    def test_lists_scenes_with_prompt_counts(self):
        with configured_dataset_roots() as roots:
            roots.write_prompt("T2I", "portrait", "a\tone\nb\ttwo\n")
            self.assertEqual(list_datasets("T2I"), [{"scene": "portrait", "prompt_count": 2}])

    def test_t2i_and_prompt_only_ti2i_return_txt_artifacts(self):
        with configured_dataset_roots() as roots:
            roots.write_prompt("T2I", "open", "a\tone\n")
            roots.write_prompt("TI2I", "edit", "b\ttwo\n")
            t2i = create_dataset_artifact("T2I", "open")
            ti2i = create_dataset_artifact("TI2I", "edit", include_ref=False)
            self.assertEqual(Path(t2i.path).read_bytes(), b"a\tone\n")
            self.assertEqual(t2i.filename, "open.txt")
            self.assertEqual(ti2i.filename, "edit.txt")
            self.assertIsNone(t2i.cleanup_dir)

    def test_rejects_unsafe_or_missing_scene_before_reading(self):
        with configured_dataset_roots():
            with self.assertRaisesRegex(AppError, "场景必须是有效的目录名"):
                create_dataset_artifact("T2I", "../secret")
            with self.assertRaisesRegex(AppError, "未找到场景 missing 的 prompt 文件"):
                create_dataset_artifact("T2I", "missing")
