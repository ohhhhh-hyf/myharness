"""知识源清单：扫描 xiaoyi/rag/data/*.md，解析文件名里的类别与标题。

文件名约定：``NN-类别-标题.md``（如 ``12-功能详解-小艺慧记会议纪要.md``）。
- file_category：中文类别（发展历程 / 核心能力 / …），用于筛选与展示；
- content_type：类别对应的英文 slug，语义同 xiaoyi_demo 的 faq/policy/manual；
- 读取时剥离 YAML frontmatter（避免其变成噪声块——实测参考项目的切块器会把
  frontmatter 当正文，作为 20 份文档的接入侧这里统一处理）。
"""
from __future__ import annotations

import re
import sys
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
