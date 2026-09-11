"""知识源清单：扫描 xiaoyi/rag/data/*.md，解析文件名里的类别与标题。

文件名约定：``NN-类别-标题.md``（如 ``12-功能详解-小艺慧记会议纪要.md``）。
- file_category：中文类别（发展历程 / 核心能力 / …），用于筛选与展示；
- content_type：类别对应的英文 slug，语义同 xiaoyi_demo 的 faq/policy/manual；
- 读取时剥离 YAML frontmatter（避免其变成噪声块——实测参考项目的切块器会把
  frontmatter 当正文，作为 20 份文档的接入侧这里统一处理）。
"""
from __future__ import annotations

import functools
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# 本文件夹自成一体：把自身目录加入模块搜索路径，直接用绝对名导入同目录模块。
_RAG_DIR = Path(__file__).resolve().parent
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

import config as rag_config  # noqa: E402

# 中文类别 → 英文 content_type（新增类别时在此登记，未知类别回退 "doc"）
CATEGORY_TYPES: dict[str, str] = {
    "发展历程": "history",
    "核心能力": "capability",
    "鸿蒙融合": "harmony",
    "功能详解": "feature",
    "设备协同": "device",
    "场景生态": "scene",
    "使用指南": "guide",
    "安全与生态": "security",
}

_FILENAME_RE = re.compile(r"^(?P<num>\d+)-(?P<cat>[^-]+)-(?P<title>.+)$")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)


@dataclass
class Source:
    name: str            # 文件名
    path: Path
    title: str           # 文件名里的标题（frontmatter 之外的兜底信息）
    file_category: str   # 中文类别
    content_type: str    # 英文 slug


def strip_frontmatter(md: str) -> str:
    return _FRONTMATTER_RE.sub("", md, count=1)


def list_sources() -> list[Source]:
    """按文件名排序返回知识源；跳过不符合命名约定的文件。"""
    out: list[Source] = []
    for path in sorted(rag_config.settings.kb_dir.glob("*.md")):
        m = _FILENAME_RE.match(path.stem)
        if not m:
            continue
        cat = m.group("cat")
        out.append(Source(
            name=path.name,
            path=path,
            title=m.group("title"),
            file_category=cat,
            content_type=CATEGORY_TYPES.get(cat, "doc"),
        ))
    return out


def read_markdown(src: Source) -> str:
    return strip_frontmatter(src.path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 门控关键词（自动生成）
# 知识库的"话题清单"其实就写在文档标题里：把每个 md 的 H1/H2 小节标题与文件名标题
# 切成短词，按**文档频率**过滤掉过于通用的词（如"常见问题""使用"），得到域内关键词表。
# 好处：新增文档后词表自动覆盖，零维护；显式设置 RAG_GATE_KEYWORDS 时以显式值为准。

_TERM_SPLIT_RE = re.compile(r"[\s：:、，。！？；;·—–/\|()（）【】\[\]{}<>《》\"'“”‘’]+")
_TERM_SPLIT_WORDS_RE = re.compile(r"[与和及的地得]+")
_LEADING_INDEX_RE = re.compile(r"^(?:[一二三四五六七八九十百千]+[、.．)）]|\d+[、.．)）]|[（(]\d+[)）])+\s*")
_TRAILING_PARTICLE_RE = re.compile(r"[上中里内等]+$")
_TERM_OK_RE = re.compile(r"^[一-鿿A-Za-z0-9]{2,12}$")

# 明确过于通用的词（即使文档频率不高也不做门控词）
_GENERIC_TERMS = {
    "常见问题", "使用", "支持", "介绍", "功能", "方式", "设置", "说明", "概览",
    "限制", "场景", "能力", "方法", "步骤", "问题", "总结", "汇总", "对照表", "总表",
    "边界", "原则", "要点", "建议", "实操", "详解", "指南", "手册", "速查", "教程", "排查",
}
_MAX_DF_RATIO = 0.35      # 出现在超过 35% 文档中的词视为通用词，剔除
_JUNK_RE = re.compile(r"[+=\d]")   # 含数字/加号/等号的词（年份、"1+8+N" 等）不做门控词


def _candidate_terms(text: str) -> list[str]:
    """把一行标题切成候选词：先按标点/空格切，再按连接词（与和及）与"的"切。"""
    out: list[str] = []
    for chunk in _TERM_SPLIT_RE.split(text or ""):
        chunk = _LEADING_INDEX_RE.sub("", chunk.strip())
        for piece in _TERM_SPLIT_WORDS_RE.split(chunk):
            piece = _TRAILING_PARTICLE_RE.sub("", piece.strip())
            if not piece or piece in _GENERIC_TERMS:
                continue
            if _TERM_OK_RE.match(piece):
                out.append(piece)
    return out


@functools.lru_cache(maxsize=1)
def gate_keywords() -> tuple[str, ...]:
    """域内关键词表：显式配置优先，否则由文档标题自动生成 + 内置基础词兜底。"""
    from config import DEFAULT_GATE_KEYWORDS, settings  # 本文件夹自成一体：绝对名导入

    explicit = settings.gate_keywords
    if explicit and tuple(explicit) != tuple(DEFAULT_GATE_KEYWORDS):
        return tuple(explicit)          # 用户显式配置 → 不自动生成

    sources = list_sources()
    df: Counter[str] = Counter()
    for src in sources:
        text = read_markdown(src)
        titles = [src.title]
        titles += [ln.lstrip("#").strip() for ln in text.splitlines() if ln.startswith("#")]
        for term in set(_candidate_terms(" ".join(titles))):
            df[term] += 1

    n_docs = max(len(sources), 1)
    auto = {
        t for t, d in df.items()
        if d <= max(2, int(n_docs * _MAX_DF_RATIO))
        and not _JUNK_RE.search(t)
        and not (t.isascii() and len(t) < 3)       # 纯英文过短（如 "vs"）不做门控词
    }
    return tuple(sorted(auto | set(DEFAULT_GATE_KEYWORDS)))


def reset_gate_keywords_cache() -> None:
    """测试用：清空自动词表缓存。"""
    gate_keywords.cache_clear()
