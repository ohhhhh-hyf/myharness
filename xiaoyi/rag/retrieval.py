"""检索编排（移植自 xiaoyi_demo/app/core/retrieval.py）。

固定全链路：bge 向量 + BM25 混合召回 → RRF 融合 → bge-reranker 精排（无模式开关）。
- 一问多意图：按标点拆子句各检索一遍，再轮转合并（同小节去重）；
- 返回最终排序的 hit（含 rerank_score），不做首尾组装（调用侧按需）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 本文件夹自成一体：把自身目录加入模块搜索路径，直接用绝对名导入同目录模块。
_RAG_DIR = Path(__file__).resolve().parent
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

import re

import embeddings as rag_embeddings
import rerank as rag_rerank
import config as rag_config
import localstore as rag_store

_CLAUSE = re.compile(r"[,，;；?？。]")
_MIN_CLAUSE = 4          # 太短的碎片（「怎么办」）当不了子查询


def split_clauses(query: str) -> list[str]:
    """把一问多意图的问题按标点拆成子句；拆不出两条就原样返回一条。"""
    parts = [p.strip() for p in _CLAUSE.split(query) if len(p.strip()) >= _MIN_CLAUSE]
    return parts if len(parts) >= 2 else [query]


def _merge_round_robin(lists: list[list[dict]]) -> list[dict]:
    """各子句轮流出一条，按 chunk id 去重；同一小节只留最靠前的那条。"""
    out: list[dict] = []
    seen_id: set = set()
    seen_sec: set = set()
    tail: list[dict] = []
    for i in range(max((len(x) for x in lists), default=0)):
        for lst in lists:
            if i >= len(lst):
                continue
            hit = lst[i]
            key = hit.get("id") or (hit.get("section_path", ""), hit.get("question", ""))
            if key in seen_id:
                continue
            seen_id.add(key)
            sec = hit.get("section_path") or ""
            if sec in seen_sec:
                tail.append(hit)
            else:
                seen_sec.add(sec)
                out.append(hit)
    return out + tail


def arrange_head_tail(items: list) -> list:
    """最相关放首、次相关放尾，其余按序居中（缓解 lost-in-the-middle）。"""
    if len(items) <= 2:
        return items
    return [items[0], *items[2:], items[1]]


async def search_knowledge(
    query: str,
    top_k: int | None = None,
    category: str | None = None,
    bm25_text: str | None = None,
    split: bool = True,
    query_vec: list[float] | None = None,
) -> list[dict]:
    """混合检索（固定链路）：dense + BM25 → RRF → bge-reranker 精排。

    query：dense 向量化与重排用的标准问法；
    bm25_text：BM25 检索文本（默认同 query；可传「标准问法 + 同义词扩展」，
    只作用于 BM25 一侧，不污染 dense）；
    query_vec：预先算好的查询向量（门控阶段已嵌入时传入，省一次 API 调用；
    一问多意图拆子句时子句仍各自嵌入）。
    """
    top_k = top_k or rag_config.settings.rerank_top_k
    bt = bm25_text or query

    # 一问多意图：按子句各检索一遍再轮转合并，免得一个意图把名额占满
    if split and rag_config.settings.subquery_split:
        clauses = split_clauses(query)
        if len(clauses) >= 2:
            per = [
                await search_knowledge(
                    c, top_k=top_k, category=category, bm25_text=bt, split=False,
                )
                for c in clauses
            ]
            return _merge_round_robin(per)[:top_k]

    # 混合召回：dense（query 向量） + BM25（bt 文本） → RRF 候选池
    vec = query_vec or await rag_embeddings.embed_query(query)
    hits = rag_store.state().hybrid_top(
        vec, bt, rag_config.settings.candidate_top_k, rag_config.settings.recall_top_k, category
    )

    # 精排：候选池送 bge-reranker
    docs = [f"{h['question']} {h['answer']}" for h in hits]
    ranked = await rag_rerank.rerank(query, docs, top_n=top_k)
    out = []
    for idx, score in ranked:
        hit = dict(hits[idx])
        hit["rerank_score"] = score
        out.append(hit)
    return out
