"""bge-reranker-v2-m3 精排（/rerank 端点，退避重试）。

移植自 xiaoyi_demo/app/core/rerank.py：rerank 不是 OpenAI 协议，
走 Jina / Cohere 那套形状（query + documents → results[index, relevance_score]），
因此手写 httpx 请求。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 本文件夹自成一体：把自身目录加入模块搜索路径，直接用绝对名导入同目录模块。
_RAG_DIR = Path(__file__).resolve().parent
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

import asyncio
import re

import httpx

import config as rag_config

_VERSION_SEG = re.compile(r"/v\d+$")
_RETRY_STATUS = {429, 500, 502, 503, 504}
_RETRIES = 3
_BACKOFF = 1.5


def _rerank_url() -> str:
    """把配置里的上游地址拼成 /rerank 端点。地址缺版本段时补 /v1。"""
    base = rag_config.settings.rerank_base_url.rstrip("/")
    if not _VERSION_SEG.search(base):
        base += "/v1"
    return base + "/rerank"


async def _post(url: str, payload: dict, headers: dict, timeout: float) -> httpx.Response:
    """带退避重试：子句拆分后一次查询要打多次 /rerank，撞 429/5xx 或连接抖动
    都当瞬时故障退避重试；连试几次仍不行才抛出去。"""
    last: httpx.Response | None = None
    last_exc: Exception | None = None
    for i in range(_RETRIES + 1):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.TransportError as e:
            last_exc = e
            if i < _RETRIES:
                await asyncio.sleep(_BACKOFF * (2 ** i))
                continue
            raise
        if resp.status_code not in _RETRY_STATUS:
            return resp
        last = resp
        if i < _RETRIES:
            await asyncio.sleep(_BACKOFF * (2 ** i))
    if last is None and last_exc is not None:
        raise last_exc
    assert last is not None
    return last


async def rerank(query: str, docs: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
    """返回 [(原始索引, 相关分)]，按分降序并截断 top_n。"""
    if not docs:
        return []
    if not rag_config.settings.rerank_api_key:
        raise RuntimeError(
            "缺少重排 API Key：请在 xiaoyi/rag/.env 配置 RERANK_API_KEY"
            "（或 SILICONFLOW_API_KEY）"
        )
    payload = {
        "model": rag_config.settings.rerank_model,
        "query": query,
        "documents": docs,
        "top_n": top_n or len(docs),
    }
    resp = await _post(
        _rerank_url(), payload,
        {"Authorization": f"Bearer {rag_config.settings.rerank_api_key}"}, 15,
    )
    resp.raise_for_status()
    results = resp.json()["results"]
    ranked = sorted(
        ((r["index"], float(r["relevance_score"])) for r in results),
        key=lambda x: x[1], reverse=True,
    )
    return ranked[:top_n] if top_n else ranked
