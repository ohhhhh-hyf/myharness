"""检索自测 CLI：不经过大模型，直接看召回/精排结果与分数。

固定全链路：bge 向量 + BM25 混合召回 → RRF 融合 → bge-reranker 精排。

用法（在项目根目录执行；需先入库）：
    python xiaoyi/rag/query.py "小艺慧记支持哪些功能"
    python xiaoyi/rag/query.py "小艺的隐私保护" --k 3
    python xiaoyi/rag/query.py "小艺帮记怎么用" --json
"""
from __future__ import annotations

import sys
from pathlib import Path

# 本文件夹自成一体：把自身目录加入模块搜索路径，直接用绝对名导入同目录模块。
_RAG_DIR = Path(__file__).resolve().parent
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

import argparse
import asyncio
import json

import config as rag_config
import localstore as rag_store
from retrieval import search_knowledge


def _snippet(text: str, width: int = 80) -> str:
    one_line = " ".join(text.split())
    return one_line[:width] + ("…" if len(one_line) > width else "")


async def main(query: str, top_k: int, as_json: bool) -> None:
    if not rag_store.load():
        print(f"知识库未就绪：{rag_store.status().get('error')}", file=sys.stderr)
        sys.exit(1)

    hits = await search_knowledge(query, top_k=top_k)

    if as_json:
        print(json.dumps(
            {"query": query, "strategy": "hybrid_rerank", "hits": hits},
            ensure_ascii=False, indent=2,
        ))
        return

    st = rag_store.status()
    print(f"问题: {query}")
    print(f"链路: 向量 + BM25 → RRF → bge 精排 | 索引 {st['chunk_total']} 块 | 模型 {st['embed_model']}")
    print("-" * 72)
    if not hits:
        print("（无召回结果）")
        return
    for i, h in enumerate(hits, start=1):
        score = h.get("rerank_score", h.get("score"))
        print(f"[{i}] rerank={score:.4f}  {h.get('section_path', '')}")
        print(f"    来源: {h.get('source_file', '')}  类别: {h.get('category', '')}")
        print(f"    问: {h.get('question', '')}")
        print(f"    答: {_snippet(h.get('answer', ''))}")
        print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="RAG 检索自测（向量 + BM25 + RRF + 精排）")
    ap.add_argument("query", help="查询问题")
    ap.add_argument("--k", type=int, default=rag_config.settings.rerank_top_k, help="返回条数")
    ap.add_argument("--json", action="store_true", help="输出 JSON（便于程序处理）")
    args = ap.parse_args()
    asyncio.run(main(args.query, args.k, args.json))
