"""bge-m3 嵌入（OpenAI 兼容端点，默认硅基流动）。

查询嵌入带 **LRU 缓存**：归一化（去空白/标点、统一小写）后相同的查询直接复用向量，
重复提问、标点差异的追问都能零 API 秒回；入库用的批量嵌入（embed_texts）不走缓存。
"""
from __future__ import annotations

import re
from collections import OrderedDict

import sys
from pathlib import Path

# 本文件夹自成一体：把自身目录加入模块搜索路径，直接用绝对名导入同目录模块。
_RAG_DIR = Path(__file__).resolve().parent
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

from openai import AsyncOpenAI

import config as rag_config

_CLIENT: AsyncOpenAI | None = None


def _client() -> AsyncOpenAI:
    """进程内单例：复用连接池，避免每次嵌入新建客户端。"""
    global _CLIENT
    if _CLIENT is None:
        if not rag_config.settings.embed_api_key:
            raise RuntimeError(
                "缺少嵌入 API Key：请在 xiaoyi/rag/.env 配置 EMBED_API_KEY"
                "（或 SILICONFLOW_API_KEY）"
            )
        _CLIENT = AsyncOpenAI(
            base_url=rag_config.settings.embed_base_url,
            api_key=rag_config.settings.embed_api_key,
            # 网络不可达时快速失败（配合检索层的自动降级）
            timeout=15.0,
            max_retries=1,
        )
    return _CLIENT


async def embed_texts(texts: list[str]) -> list[list[float]]:
    resp = await _client().embeddings.create(model=rag_config.settings.embed_model, input=texts)
    return [d.embedding for d in resp.data]


# 缓存键归一化：去掉空白与中英文标点，统一小写
_CACHE_KEY_RE = re.compile(r"[\s，。！？；：、,.!?;:'\"()（）【】\[\]{}<>《》…—\-]+")

_QUERY_CACHE: "OrderedDict[str, list[float]]" = OrderedDict()


def _cache_key(text: str) -> str:
    return _CACHE_KEY_RE.sub("", text or "").lower()


async def embed_query(text: str, use_cache: bool = True) -> list[float]:
    """查询嵌入；命中 LRU 缓存时直接返回（不发起网络请求）。"""
    key = _cache_key(text)
    if use_cache and key:
        cache_key = f"{rag_config.settings.embed_model}|{key}"
        cached = _QUERY_CACHE.get(cache_key)
        if cached is not None:
            _QUERY_CACHE.move_to_end(cache_key)
            return list(cached)
    else:
        cache_key = ""

    vec = (await embed_texts([text]))[0]
    if cache_key:
        while len(_QUERY_CACHE) >= rag_config.settings.query_cache_size:
            _QUERY_CACHE.popitem(last=False)
        _QUERY_CACHE[cache_key] = list(vec)
    return vec


def cache_stats() -> dict:
    return {"size": len(_QUERY_CACHE), "max": rag_config.settings.query_cache_size}


def reset_query_cache() -> None:
    """测试用：清空查询嵌入缓存。"""
    _QUERY_CACHE.clear()
