from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from xiaoyi.conversation import Attachment, Message

# 把 provider 无关的内部消息序列化成各家 API 的请求格式。
# 这一层属于「适配器」职责，对话层（ConversationManager）只管消息、不懂线上格式。

# 单张图片的发送上限；超过则降级为文字说明，避免请求体过大。
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# 编码结果缓存：键为 (路径, mtime_ns, 大小)，同一张图每轮只编码一次。
_ENCODE_CACHE: dict[tuple[str, int, int], tuple[str, str] | None] = {}
_ENCODE_CACHE_LIMIT = 8


def _attachment_name(att: Attachment) -> str:
    return Path(att.path).name or att.path


def _load_image_base64(att: Attachment) -> tuple[str, str] | None:
    """读取附件并编码为 (media_type, base64)；失败或超限返回 None。"""
    try:
        stat = Path(att.path).stat()
    except OSError:
        return None
    if stat.st_size > MAX_IMAGE_BYTES:
        return None

    key = (att.path, stat.st_mtime_ns, stat.st_size)
    if key in _ENCODE_CACHE:
        return _ENCODE_CACHE[key]

    try:
        data = Path(att.path).read_bytes()
    except OSError:
        return None
    encoded = (att.media_type, base64.b64encode(data).decode("ascii"))
    if len(_ENCODE_CACHE) >= _ENCODE_CACHE_LIMIT:
        _ENCODE_CACHE.pop(next(iter(_ENCODE_CACHE)))
    _ENCODE_CACHE[key] = encoded
    return encoded


def _image_note(att: Attachment) -> str:
    """图片无法内联发送时的文字占位说明。"""
    try:
        size = Path(att.path).stat().st_size
    except OSError:
        return f"[图片缺失: {_attachment_name(att)}]"
    if size > MAX_IMAGE_BYTES:
        return f"[图片过大未发送: {_attachment_name(att)}（{size / 1024 / 1024:.1f}MB）]"
    return f"[图片读取失败: {_attachment_name(att)}]"


def _vision_note(att: Attachment) -> str:
    return f"[图片未发送: {_attachment_name(att)}（当前 provider 未启用 vision）]"


def _resolve_images(
    attachments: list[Attachment], vision: bool
) -> tuple[list[tuple[str, str]], list[str]]:
    """把附件解析为 (可内联图片, 文字补充) 两部分。"""
    images: list[tuple[str, str]] = []
    notes: list[str] = []
    for att in attachments:
        if not vision:
            notes.append(_vision_note(att))
            continue
        encoded = _load_image_base64(att)
        if encoded is None:
            notes.append(_image_note(att))
        else:
            images.append(encoded)
    return images, notes


def build_anthropic_messages(
    messages: list[Message], vision: bool = True
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.tool_uses or m.thinking_blocks:
            content: list[dict[str, Any]] = []
            for tb in m.thinking_blocks:
                content.append({
                    "type": "thinking",
                    "thinking": tb.thinking,
                    "signature": tb.signature,
                })
            if m.content:
                content.append({"type": "text", "text": m.content})
            for tu in m.tool_uses:
                content.append({
                    "type": "tool_use",
                    "id": tu.tool_use_id,
                    "name": tu.tool_name,
                    "input": tu.arguments,
                })
            if not content:
                content.append({"type": "text", "text": ""})
            result.append({"role": "assistant", "content": content})
        elif m.tool_results:
            content = []
            for tr in m.tool_results:
                content.append({
                    "type": "tool_result",
                    "tool_use_id": tr.tool_use_id,
                    "content": tr.content,
                    "is_error": tr.is_error,
                })
            result.append({"role": "user", "content": content})
        elif m.attachments:
            images, notes = _resolve_images(m.attachments, vision)
            content = []
            for media_type, data in images:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": data,
                    },
                })
            text = m.content
            if notes:
                text = (text + "\n" + "\n".join(notes)) if text else "\n".join(notes)
            if text:
                content.append({"type": "text", "text": text})
            result.append({"role": "user", "content": content})
        else:
            # 合并连续的 user 纯文本消息（system-reminder 或普通 user 文本）。
            # 不合并到 tool_result / 图片类型的 user 消息中（content 是 list）。
            if (
                m.role == "user"
                and result
                and result[-1]["role"] == "user"
                and isinstance(result[-1]["content"], str)
            ):
                result[-1]["content"] = result[-1]["content"] + "\n" + m.content
            else:
                result.append({"role": m.role, "content": m.content})
    return result


def build_openai_input(
    messages: list[Message], vision: bool = True
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.tool_uses:
            if m.content:
                result.append({"role": "assistant", "content": m.content})
            for tu in m.tool_uses:
                result.append({
                    "type": "function_call",
                    "name": tu.tool_name,
                    "call_id": tu.tool_use_id,
                    "arguments": json.dumps(tu.arguments),
                })
        elif m.tool_results:
            for tr in m.tool_results:
                result.append({
                    "type": "function_call_output",
                    "call_id": tr.tool_use_id,
                    "output": tr.content,
                })
        elif m.attachments:
            images, notes = _resolve_images(m.attachments, vision)
            content: list[dict[str, Any]] = []
            for media_type, data in images:
                content.append({
                    "type": "input_image",
                    "image_url": f"data:{media_type};base64,{data}",
                })
            text = m.content
            if notes:
                text = (text + "\n" + "\n".join(notes)) if text else "\n".join(notes)
            if text:
                content.append({"type": "input_text", "text": text})
            result.append({"role": "user", "content": content})
        else:
            result.append({"role": m.role, "content": m.content})
    return result


def build_chat_completion_messages(
    messages: list[Message], vision: bool = True
) -> list[dict[str, Any]]:
    """OpenAI Chat Completions 格式。

    - 用户消息：{"role": "user", "content": "..."}；带图片附件时 content 为
      多模态块列表（image_url + text）
    - 助手文本+工具调用：{"role": "assistant", "content": "...", "tool_calls": [...]}
    - 工具结果：{"role": "tool", "tool_call_id": "...", "content": "..."}
    - thinking 块被跳过（Chat Completions 不支持）。
    """
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.tool_uses:
            tool_calls = []
            for tu in m.tool_uses:
                tool_calls.append({
                    "id": tu.tool_use_id,
                    "type": "function",
                    "function": {
                        "name": tu.tool_name,
                        "arguments": json.dumps(tu.arguments),
                    },
                })
            result.append({
                "role": "assistant",
                "content": m.content or None,
                "tool_calls": tool_calls,
            })
        elif m.tool_results:
            for tr in m.tool_results:
                result.append({
                    "role": "tool",
                    "tool_call_id": tr.tool_use_id,
                    "content": tr.content,
                })
        elif m.attachments:
            images, notes = _resolve_images(m.attachments, vision)
            content: list[dict[str, Any]] = []
            for media_type, data in images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{data}"},
                })
            text = m.content
            if notes:
                text = (text + "\n" + "\n".join(notes)) if text else "\n".join(notes)
            if text:
                content.append({"type": "text", "text": text})
            result.append({"role": "user", "content": content})
        else:
            result.append({"role": m.role, "content": m.content})
    return result


def build_messages(
    messages: list[Message], protocol: str = "anthropic", vision: bool = True
) -> list[dict[str, Any]]:
    if protocol == "openai":
        return build_openai_input(messages, vision=vision)
    if protocol == "openai-compat":
        return build_chat_completion_messages(messages, vision=vision)
    return build_anthropic_messages(messages, vision=vision)
