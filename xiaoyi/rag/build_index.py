"""知识库入库 CLI：把 xiaoyi/rag/data/*.md 切块 + 嵌入，写入本地索引。

用法（在项目根目录执行）：
    python xiaoyi/rag/build_index.py            # 缓存命中则直接返回；文档有改动/首次则联网入库
    python xiaoyi/rag/build_index.py --force    # 无视缓存，全量重新嵌入
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
import sys

import localstore as rag_store


async def main(force: bool) -> None:
    ready = rag_store.load()
    if ready and not force:
        st = rag_store.status()
        print(f"OK 知识库已就绪（缓存命中，无需联网）：{st['chunk_total']} 块，"
              f"构建于 {st['built_at']} · 模型 {st['embed_model']}")
        if st.get("stale"):
            print(f"   注意：索引与当前环境存在差异（{st['stale']}）——"
                  f"已按宽松模式加载；如需精确请 --force 重建")
        for f in st.get("files", []):
            print(f"   - {f['name']}: {f['chunks']} 块")
        return

    reason = "" if force else f"（{rag_store.status().get('error')}）"
    print(f"-> 开始入库{reason} ...")
    try:
        info = await rag_store.build(force=True)
    except rag_store.IndexNotReady as e:
        print(f"XX 入库失败: {e}", file=sys.stderr)
        print("   请检查 xiaoyi/rag/.env 的 EMBED_API_KEY / EMBED_MODEL 与网络后重试",
              file=sys.stderr)
        sys.exit(1)

    st = rag_store.status()
    print(f"OK 入库完成：共 {info['chunks']} 块 · 嵌入模型 {st['embed_model']} · {info['built_at']}")
    print(f"   索引文件: {st['index_path']}")
    for f in info.get("files", []):
        print(f"   - {f['name']}: {f['chunks']} 块")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="RAG 知识库入库（切块 + 嵌入 + 写本地索引）")
    ap.add_argument("--force", action="store_true", help="无视缓存，全量重新嵌入")
    args = ap.parse_args()
    asyncio.run(main(args.force))
