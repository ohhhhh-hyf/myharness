"""bge-m3 嵌入（OpenAI 兼容端点，默认硅基流动）。"""
from __future__ import annotations

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
            base_url=rag_config.settings.embed_base_url, api_key=rag_config.settings.embed_api_key
        )
    return _CLIENT


async def embed_texts(texts: list[str]) -> list[list[float]]:
    resp = await _client().embeddings.create(model=rag_config.settings.embed_model, input=texts)
    return [d.embedding for d in resp.data]


async def embed_query(text: str) -> list[float]:
    return (await embed_texts([text]))[0]
