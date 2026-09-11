"""上游服务可用性熔断（嵌入 / 重排）。

检索链默认走"在线嵌入 + 在线精排"（硅基流动）。当网络不可达或服务异常时：

- 记录**降级原因**与**熔断截止时间**（默认 5 分钟），期间跳过对应调用、直接走
  本地降级路径（嵌入不可用 → 纯 BM25；重排不可用 → 用 RRF 融合顺序）；
- 这样"服务器不能出网"也能检索（质量略降、无精排），且不会每轮都撞网络超时。
"""
from __future__ import annotations

import time

BREAKER_SECONDS = 300.0

_embed_down_until = 0.0
_rerank_down_until = 0.0
_embed_reason = ""
_rerank_reason = ""


def _reason(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}".strip()[:160]


def embed_available() -> bool:
    return time.monotonic() >= _embed_down_until


def rerank_available() -> bool:
    return time.monotonic() >= _rerank_down_until


def mark_embed_down(exc: Exception) -> None:
    global _embed_down_until, _embed_reason
    _embed_down_until = time.monotonic() + BREAKER_SECONDS
    _embed_reason = _reason(exc)


def mark_rerank_down(exc: Exception) -> None:
    global _rerank_down_until, _rerank_reason
    _rerank_down_until = time.monotonic() + BREAKER_SECONDS
    _rerank_reason = _reason(exc)


def embed_reason() -> str:
    return _embed_reason if not embed_available() else ""


def rerank_reason() -> str:
    return _rerank_reason if not rerank_available() else ""


def mode() -> str:
    """当前检索链路：full / no_rerank / bm25_only。"""
    if not embed_available():
        return "bm25_only"
    if not rerank_available():
        return "no_rerank"
    return "full"


def note() -> str:
    """给用户/模型看的降级说明（正常时为空串）。"""
    m = mode()
    if m == "bm25_only":
        return f"嵌入服务不可达（{embed_reason()}），已降级为本地关键词检索（BM25，不联网）"
    if m == "no_rerank":
        return f"重排服务不可达（{rerank_reason()}），已跳过精排（按 RRF 融合顺序）"
    return ""


def reset() -> None:
    """测试用：清除熔断状态。"""
    global _embed_down_until, _rerank_down_until, _embed_reason, _rerank_reason
    _embed_down_until = _rerank_down_until = 0.0
    _embed_reason = _rerank_reason = ""
