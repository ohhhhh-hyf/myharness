"""Markdown 切块工具（移植自 xiaoyi_demo/app/kb/chunking.py，去掉 langchain 依赖）。

三件事：
1. ``split_sections``：按 h1~h4 标题把 md 切成小节（正文不含标题行）；
2. ``recursive_split``：中文友好的递归切分（段落 → 换行 → 句末标点 → 逐字）；
3. 表格与句级重叠：大表格按行切并重贴表头；正文切块后按**完整句**做重叠。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 与参考项目一致：只按 1~4 级标题分节
HEADER_LEVELS = (1, 2, 3, 4)
_HEADER_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*$")

# 中文无词边界：分隔符优先段落/换行，再句末标点，最后逐字
CJK_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "!", "?", ";", "，", " ", ""]


@dataclass
class Section:
    headers: list[tuple[int, str]] = field(default_factory=list)  # [(level, title)]
    body: str = ""


def split_sections(md: str) -> list[Section]:
    """按标题层级分节；维护标题栈，输出每节的标题路径与正文。"""
    sections: list[Section] = []
    stack: dict[int, str] = {}
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append(Section(
                headers=[(lv, stack[lv]) for lv in sorted(stack)],
                body=body,
            ))

    for line in md.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            flush()
            buf = []
            level = len(m.group(1))
            title = m.group(2).strip()
            for lv in [lv for lv in stack if lv >= level]:
                del stack[lv]
            stack[level] = title
        else:
            buf.append(line)
    flush()
    return sections


def recursive_split(
    text: str, chunk_size: int, separators: list[str] | None = None
) -> list[str]:
    """递归切分：按分隔符优先拆分，合并小片段，超长片段降级用更细分隔符。"""
    separators = separators if separators is not None else CJK_SEPARATORS
    if len(text) <= chunk_size:
        return [text] if text else []

    sep = next((s for s in separators if s and s in text), "")
    if not sep:  # 无可用分隔符：硬切
        return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    parts = text.split(sep)
    pieces = [p + sep for p in parts[:-1]]
    if parts[-1]:
        pieces.append(parts[-1])

    merged: list[str] = []
    cur = ""
    for piece in pieces:
        if cur and len(cur) + len(piece) > chunk_size:
            merged.append(cur)
            cur = piece
        else:
            cur += piece
    if cur:
        merged.append(cur)

    rest = separators[separators.index(sep) + 1:]
    out: list[str] = []
    for chunk in merged:
        if len(chunk) <= chunk_size:
            out.append(chunk)
        else:
            out.extend(recursive_split(chunk, chunk_size, rest))
    return out


_SENT_RE = re.compile(r"[^。！？!?…\n]*[。！？!?…\n]|[^。！？!?…\n]+$")


def _split_sentences(text: str) -> list[str]:
    return [m for m in _SENT_RE.findall(text) if m]


def _trailing_sentences(text: str, max_chars: int) -> str:
    """取结尾若干**完整句**作为重叠，总长尽量不超过 max_chars；
    单句超长则整句保留（优先「不留半截话」）。"""
    out: list[str] = []
    total = 0
    for sentence in reversed(_split_sentences(text)):
        if out and total + len(sentence) > max_chars:
            break
        out.insert(0, sentence)
        total += len(sentence)
    return "".join(out)


def apply_sentence_overlap(chunks: list[str], overlap: int) -> list[str]:
    if not chunks:
        return []
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        ov = _trailing_sentences(chunks[i - 1], overlap)
        out.append(ov + chunks[i] if ov else chunks[i])
    return out


_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _find_table_header(lines: list[str]) -> int:
    """返回表头行下标（其后紧跟 --- 分隔行）；无表格返回 -1。
    允许表格前有若干散文行（不要求首行即表头）。"""
    for i in range(len(lines) - 1):
        if (lines[i].lstrip().startswith("|")
                and _TABLE_SEP_RE.match(lines[i + 1]) and "-" in lines[i + 1]):
            return i
    return -1


def is_table_block(text: str) -> bool:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return _find_table_header(lines) != -1


def split_table_rows(table_md: str, max_rows: int) -> list[str]:
    """大表格按行切，每块重贴表头行 + 分隔行；不超 max_rows 数据行则整块返回。
    表头前的散文行作为前言保留在首块。"""
    lines = [ln for ln in table_md.strip().splitlines() if ln.strip()]
    idx = _find_table_header(lines)
    if idx == -1:
        return [table_md.strip()]
    preamble, header, sep, rows = lines[:idx], lines[idx], lines[idx + 1], lines[idx + 2:]
    if len(rows) <= max_rows:
        return [table_md.strip()]
    out: list[str] = []
    for j, i in enumerate(range(0, len(rows), max_rows)):
        group = rows[i:i + max_rows]
        block = [*preamble, header, sep, *group] if j == 0 else [header, sep, *group]
        out.append("\n".join(block))
    return out
