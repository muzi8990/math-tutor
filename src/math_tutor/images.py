"""Validate and normalize local images or base64 data URLs."""

import base64
import binascii
import io
from pathlib import Path
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 16_000_000
FORMATS = {"PNG", "JPEG", "WEBP"}
MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


def load_image(source: str | Path, *, max_bytes: int = MAX_IMAGE_BYTES) -> tuple[bytes, str]:
    """Return a single-frame PNG with orientation applied and metadata removed."""
    if isinstance(source, str) and source.startswith("data:"):
        header, separator, encoded = source.partition(",")
        if not separator or header not in {f"data:{mime};base64" for mime in MIME_TYPES}:
            raise ValueError("图片 data URL 必须为 PNG、JPEG 或 WebP 的 base64 格式。")
        if len(encoded) > 4 * ((max_bytes + 2) // 3):
            raise ValueError("图片超过大小限制。")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("图片 base64 无效。") from exc
    else:
        with Path(source).open("rb") as stream:
            raw = stream.read(max_bytes + 1)
    if not raw or len(raw) > max_bytes:
        raise ValueError("图片为空或超过大小限制。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                if probe.format not in FORMATS:
                    raise ValueError("仅支持 PNG、JPEG 和 WebP 图片。")
                if probe.width * probe.height > MAX_PIXELS or getattr(probe, "n_frames", 1) != 1:
                    raise ValueError("图片像素过多或包含多个帧，请裁剪为单张题目图片。")
                probe.verify()
            with Image.open(io.BytesIO(raw)) as original:
                normalized = ImageOps.exif_transpose(original).convert("RGB")
                normalized.info.clear()
                buffer = io.BytesIO()
                normalized.save(buffer, format="PNG")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("无法读取图片，请提供完整有效的图片文件。") from exc
    data = buffer.getvalue()
    if len(data) > max_bytes:
        raise ValueError("标准化后的图片超过大小限制，请裁剪或缩小图片。")
    return data, "image/png"
