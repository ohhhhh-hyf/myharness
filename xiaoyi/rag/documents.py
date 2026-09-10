"""文档 → 结构化块（语义与 xiaoyi_demo/app/kb/documents.py 一致）。

一条小节 = 一个块：
- ``category``     ：文档标题（h1；无则用 content_type）——用于嵌入文本与筛选
- ``questions``    ：最深一级小节标题（天然对应"问"）
- ``answer``       ：该小节正文（切块后）——对应"答"
- ``section_path`` ：h1 / h2 / h3 … 全路径（引用定位用）
- ``is_key_clause``：标题+正文前 40 字命中关键条款词的打标（供后续置信度闸使用）

本项目补充字段：``source_file``（文件名）、``file_category``（中文类别）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 本文件夹自成一体：把自身目录加入模块搜索路径，直接用绝对名导入同目录模块。
_RAG_DIR = Path(__file__).resolve().parent
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

from dataclasses import dataclass

import chunking as rag_chunking

# 关键条款词表：参考项目面向电商客服（退款/运费/…），这里换成小艺语料里
# 需要"精确引用、不能含糊"的说法。仅做打标，不参与检索过滤。
_KEY_TERMS = ("版本", "限制", "不支持", "收费", "免费", "隐私", "权限", "时效")
KEY_TERMS = _KEY_TERMS


@dataclass
class Chunk:
    category: str
    questions: str
    answer: str
    section_path: str
    content_type: str
    is_key_clause: int = 0
    source_file: str = ""
    file_category: str = ""


def _is_key(title: str, body: str) -> int:
    head = title + body[:40]
    return int(any(t in head for t in _KEY_TERMS))


def build_chunks(
    md: str,
    content_type: str,
    source_file: str = "",
    file_category: str = "",
    chunk_size: int = 500,
    overlap: int = 100,
    table_max_rows: int = 10,
) -> list[Chunk]:
    out: list[Chunk] = []
    for sec in rag_chunking.split_sections(md):
        path = [title for _, title in sec.headers]
        section_path = " / ".join(path)
        title = path[-1] if path else (source_file or content_type)
        category = path[0] if path else content_type

        body = sec.body.strip()
        if not body:
            continue
        if rag_chunking.is_table_block(body):
            pieces = rag_chunking.split_table_rows(body, table_max_rows)
        else:
            base = rag_chunking.recursive_split(body, chunk_size)
            pieces = rag_chunking.apply_sentence_overlap(base, overlap)
        for piece in pieces:
            out.append(Chunk(
                category=category,
                questions=title,
                answer=piece,
                section_path=section_path,
                content_type=content_type,
                is_key_clause=_is_key(title, piece),
                source_file=source_file,
                file_category=file_category,
            ))
    return out
