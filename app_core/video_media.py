"""Video decoding helpers backed by the managed imageio-ffmpeg binary."""

import io
import subprocess

import imageio_ffmpeg
from PIL import Image, UnidentifiedImageError

from .errors import AppError


def extract_first_frame_webp(source: str, max_size: int = 256) -> bytes:
    try:
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-i",
            source,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ]
        completed = subprocess.run(
            command, capture_output=True, timeout=30, check=False
        )
        if completed.returncode != 0 or not completed.stdout:
            raise AppError("视频无法提取首帧")
        with Image.open(io.BytesIO(completed.stdout)) as opened:
            frame = opened.convert("RGB")
            frame.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            frame.save(output, format="WEBP", quality=82, method=4)
            return output.getvalue()
    except AppError:
        raise
    except (
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        UnidentifiedImageError,
    ) as exc:
        raise AppError("视频无法提取首帧") from exc
