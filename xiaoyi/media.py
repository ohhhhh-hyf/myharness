"""图片文件类型识别（供输入附件识别与权限沙箱共用）。"""

from __future__ import annotations

import os

# 可作为附件发送 / 可被工具读取的图片类型。
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def image_media_type(path: str) -> str | None:
    """返回图片路径对应的媒体类型；非图片返回 None。"""
    return IMAGE_MEDIA_TYPES.get(os.path.splitext(path)[1].lower())


def is_image_path(path: str) -> bool:
    return image_media_type(path) is not None
