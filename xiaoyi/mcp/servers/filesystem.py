"""随项目分发的文件系统 MCP server（stdio 传输）。

官方只提供 Node 版（@modelcontextprotocol/server-filesystem），启动要经 npx 解析并下载依赖；
内网/公司网络里这一步经常不可靠（遇到过 npx 缓存半装、子进程启动即 ERR_MODULE_NOT_FOUND）。
本项目是 Python 项目、mcp SDK 本来就是依赖，所以在这里用 SDK 实现一份等价物：
`uv run xiaoyi-fs <允许目录> ...` —— 不联网、不依赖 Node。

工具名与官方 Node 版逐一对齐（14 个里的 12 个，少的是 read_file（read_text_file 的别名）与
read_media_file（图片交给 harness 自己的读图能力，MCP 这层不做 base64 回传））。

两个刻意为之的取舍：
- 参数不用 `X | None` 这类联合类型。harness 生成工具参数模型时只认 schema 顶层的 type，
  联合类型会退化成字符串，所以可选数值统一写成「0 = 不限制」，可选列表用空列表做默认值。
- 所有路径过沙箱：只有 argv 给出的目录及其子目录可访问，`..` 与指向外部的符号链接在
  resolve() 之后都会被拒掉。
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import stat
import sys
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

_ALLOWED_DIRS: list[Path] = []

# 目录树一次最多吐这么多条目，避免在大仓库上把上下文撑爆
_MAX_TREE_ENTRIES = 2000

server = FastMCP("filesystem")


def _resolve(raw: str) -> Path:
    """把参数路径解析成绝对路径，并确认它落在允许目录内。

    先 resolve() 再比前缀：`../` 和指向外部的符号链接都会在这一步现形，否则
    allowed/../../secret 这种写法能溜出沙箱。Windows 路径大小写不敏感，比较时 normcase。
    """
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    resolved = p.resolve()
    key = os.path.normcase(str(resolved))
    for root in _ALLOWED_DIRS:
        prefix = os.path.normcase(str(root)).rstrip("\\/")
        if key == prefix or key.startswith(prefix + os.sep):
            return resolved
    allowed = "、".join(str(r) for r in _ALLOWED_DIRS)
    raise ValueError(f"路径不在允许目录内：{resolved}（允许的目录：{allowed}）")


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _kind_label(p: Path) -> str:
    return "[DIR]  " if p.is_dir() else "[FILE] "


@server.tool()
def list_allowed_directories() -> str:
    """列出本 server 允许访问的目录。所有文件操作只能在这些目录内进行。"""
    return "允许访问的目录：\n" + "\n".join(str(r) for r in _ALLOWED_DIRS)


@server.tool()
def read_text_file(path: str, head: int = 0, tail: int = 0) -> str:
    """按 UTF-8 读取文本文件内容。

    Args:
        path: 文件路径（绝对路径，或相对当前工作目录）。
        head: 只取前 N 行；0 表示不限。分页读大文件用。
        tail: 只取后 N 行；0 表示不限。head 与 tail 同时给出时返回「前 N 行 + 省略提示 + 后 M 行」。
    """
    f = _resolve(path)
    if not f.is_file():
        raise ValueError(f"不是文件或文件不存在：{f}")
    text = f.read_text(encoding="utf-8", errors="replace")
    if head <= 0 and tail <= 0:
        return text
    lines = text.splitlines()
    if head > 0 and tail > 0:
        if head + tail >= len(lines):
            return text
        omitted = len(lines) - head - tail
        return "\n".join([*lines[:head], f"... [{omitted} 行省略] ...", *lines[-tail:]])
    return "\n".join(lines[:head] if head > 0 else lines[-tail:])


@server.tool()
def read_multiple_files(paths: list[str]) -> str:
    """一次读取多个文件；单个文件失败不影响其余文件，错误写在对应条目里。

    Args:
        paths: 文件路径列表。
    """
    chunks: list[str] = []
    for raw in paths:
        try:
            f = _resolve(raw)
            if not f.is_file():
                raise ValueError("不是文件或文件不存在")
            chunks.append(f"{f}:\n{f.read_text(encoding='utf-8', errors='replace')}")
        except Exception as e:  # 单个文件的问题不该拖垮整批读取
            chunks.append(f"{raw}: 读取失败 - {e}")
    return "\n---\n".join(chunks)


@server.tool()
def write_file(path: str, content: str) -> str:
    """写入文本文件（整体覆盖）；父目录不存在时自动创建。

    Args:
        path: 文件路径。
        content: 要写入的完整内容。
    """
    f = _resolve(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f"已写入 {f}（{len(content)} 字符）"


class FileEdit(BaseModel):
    """一处替换：把 oldText 原样替换成 newText。"""

    oldText: str = Field(description="要被替换的原文，需要在文件中唯一匹配")
    newText: str = Field(description="替换成的新文本")


def _find_span(content: str, old: str) -> tuple[int, int]:
    """定位 old 在 content 中的区间；精确匹配优先，失败后退回「空白不敏感」匹配。

    空白不敏感这一层是必要的：模型复述原文时经常把缩进、换行写走形，只做精确匹配它会
    反复失败。匹配到多处一律报错让它补上下文，免得改错地方。
    """
    count = content.count(old)
    if count == 1:
        start = content.index(old)
        return start, start + len(old)
    if count > 1:
        raise ValueError(f"原文匹配到 {count} 处，请多带一点上下文（前后各多一两行）再试")

    tokens = old.split()
    if not tokens:
        raise ValueError("oldText 不能为空或只有空白")
    pattern = re.compile(r"\s+".join(re.escape(t) for t in tokens))
    matches = list(pattern.finditer(content))
    if not matches:
        raise ValueError("原文在文件中找不到（精确匹配与空白不敏感匹配都失败）")
    if len(matches) > 1:
        raise ValueError(f"原文匹配到 {len(matches)} 处，请多带一点上下文再试")
    m = matches[0]
    return m.start(), m.end()


@server.tool()
def edit_file(path: str, edits: list[FileEdit], dry_run: bool = False) -> str:
    """按顺序对文件做若干处文本替换。

    Args:
        path: 文件路径。
        edits: 替换列表，每项含 oldText（被替换的原文）与 newText（新文本）。
        dry_run: 为 true 时只报告替换能否成功，不写入文件。
    """
    f = _resolve(path)
    if not f.is_file():
        raise ValueError(f"不是文件或文件不存在：{f}")
    new_content = f.read_text(encoding="utf-8")
    for edit in edits:
        start, end = _find_span(new_content, edit.oldText)
        new_content = new_content[:start] + edit.newText + new_content[end:]
    if dry_run:
        return f"[dry-run] {f}：{len(edits)} 处替换均可应用，未写入"
    f.write_text(new_content, encoding="utf-8")
    return f"已修改 {f}：{len(edits)} 处替换"


@server.tool()
def create_directory(path: str) -> str:
    """创建目录（父目录会递归创建；已存在时也算成功）。

    Args:
        path: 目录路径。
    """
    d = _resolve(path)
    existed = d.is_dir()
    d.mkdir(parents=True, exist_ok=True)
    return f"目录已存在：{d}" if existed else f"已创建目录：{d}"


@server.tool()
def list_directory(path: str) -> str:
    """列出目录下的条目（目录在前，各自按名称排序）。

    Args:
        path: 目录路径。
    """
    d = _resolve(path)
    if not d.is_dir():
        raise ValueError(f"不是目录或不存在：{d}")
    entries = sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    if not entries:
        return f"{d}：（空目录）"
    lines = [f"{_kind_label(p)}{p.name}" for p in entries]
    return f"{d} 共 {len(entries)} 项：\n" + "\n".join(lines)


@server.tool()
def list_directory_with_sizes(path: str, sort_by: str = "name") -> str:
    """列出目录条目及其大小，并给出合计（排查大文件用）。

    Args:
        path: 目录路径。
        sort_by: 排序方式：name（名称）或 size（大小，降序）。
    """
    d = _resolve(path)
    if not d.is_dir():
        raise ValueError(f"不是目录或不存在：{d}")
    rows = [(p, p.stat().st_size if p.is_file() else 0) for p in d.iterdir()]
    if sort_by == "size":
        rows.sort(key=lambda r: r[1], reverse=True)
    else:
        rows.sort(key=lambda r: r[0].name.lower())
    if not rows:
        return f"{d}：（空目录）"
    total = sum(size for _, size in rows)
    lines = [f"{_kind_label(p)}{_human_size(size)}  {p.name}" for p, size in rows]
    return f"{d} 共 {len(rows)} 项，合计 {_human_size(total)}：\n" + "\n".join(lines)


@server.tool()
def directory_tree(path: str) -> str:
    """以 JSON 形式返回目录树（不跟随符号链接，条目超过上限会截断）。

    Args:
        path: 目录路径。
    """
    root = _resolve(path)
    if not root.is_dir():
        raise ValueError(f"不是目录或不存在：{root}")
    counter = {"n": 0, "truncated": False}

    def walk(d: Path) -> list[dict]:
        children: list[dict] = []
        for p in sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if counter["n"] >= _MAX_TREE_ENTRIES:
                counter["truncated"] = True
                break
            counter["n"] += 1
            if p.is_symlink():
                # 符号链接只报类型不深入，避免指回上层目录时无限递归
                children.append({"name": p.name, "type": "directory" if p.is_dir() else "file"})
            elif p.is_dir():
                children.append({"name": p.name, "type": "directory", "children": walk(p)})
            else:
                children.append({"name": p.name, "type": "file"})
        return children

    tree = {"name": root.name, "type": "directory", "children": walk(root)}
    note = "（条目数超过上限，已截断）" if counter["truncated"] else ""
    return json.dumps(tree, ensure_ascii=False) + note


@server.tool()
def move_file(source: str, destination: str) -> str:
    """移动或重命名文件/目录；目标已存在时拒绝执行。

    Args:
        source: 源路径。
        destination: 目标路径。
    """
    src = _resolve(source)
    dst = _resolve(destination)
    if not src.exists():
        raise ValueError(f"源路径不存在：{src}")
    if dst.exists():
        raise ValueError(f"目标已存在，未做任何改动：{dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"已移动：{src} → {dst}"


@server.tool()
def search_files(path: str, pattern: str, exclude_patterns: list[str] = []) -> str:
    """按 glob 模式递归搜索文件，返回匹配的完整路径。

    Args:
        path: 搜索起点目录。
        pattern: glob 模式，如 *.py、**/*.md。
        exclude_patterns: 排除用的 glob 模式，同时按相对路径与文件名匹配，如 node_modules/*。
    """
    root = _resolve(path)
    if not root.is_dir():
        raise ValueError(f"不是目录或不存在：{root}")
    hits: list[str] = []
    for p in root.rglob(pattern):
        rel = p.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(p.name, pat)
               for pat in exclude_patterns):
            continue
        hits.append(str(p))
    if not hits:
        return f"没有匹配 {pattern} 的条目（搜索目录：{root}）"
    hits.sort()
    return f"匹配 {pattern} 的条目（{len(hits)} 个）：\n" + "\n".join(hits)


@server.tool()
def get_file_info(path: str) -> str:
    """返回文件/目录的元信息：类型、大小、时间戳、权限。

    Args:
        path: 文件或目录路径。
    """
    p = _resolve(path)
    if not p.exists():
        raise ValueError(f"路径不存在：{p}")
    st = p.stat()
    kind = "directory" if p.is_dir() else "file" if p.is_file() else "other"
    return "\n".join([
        f"路径: {p}",
        f"类型: {kind}",
        f"大小: {st.st_size} 字节",
        f"创建时间: {_fmt_time(st.st_ctime)}",
        f"修改时间: {_fmt_time(st.st_mtime)}",
        f"访问时间: {_fmt_time(st.st_atime)}",
        f"权限: {stat.filemode(st.st_mode)}",
    ])


def main() -> None:
    """入口：xiaoyi-fs <允许目录> [更多目录 ...]，以 stdio 传输运行。

    目录不存在直接退出并报错：宁可启动失败，也不要变成「连得上但每个操作都被沙箱拒绝」
    的半死状态——那在客户端只会表现为一句笼统的 Connection closed。
    """
    raw_dirs = sys.argv[1:]
    if not raw_dirs:
        print("用法：xiaoyi-fs <允许目录> [更多目录 ...]", file=sys.stderr)
        raise SystemExit(2)

    roots: list[Path] = []
    for raw in raw_dirs:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        p = p.resolve()
        if not p.is_dir():
            print(f"目录不存在或不可访问：{p}", file=sys.stderr)
            raise SystemExit(1)
        roots.append(p)

    _ALLOWED_DIRS[:] = roots
    print(f"filesystem MCP server 启动，允许目录：{'、'.join(str(r) for r in roots)}",
          file=sys.stderr)
    server.run(transport="stdio")


if __name__ == "__main__":
    # 支持 `uv run python -m xiaoyi.mcp.servers.filesystem <目录>`：
    # 控制台脚本 xiaoyi-fs 需要 uv sync 落盘，而 python -m 任何时候都能起
    main()
