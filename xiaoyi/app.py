from __future__ import annotations

import asyncio
import os
import random
import time as _time
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message as TMessage
from textual.widgets import Markdown, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from xiaoyi.agent import (
    Agent,
    CompactNotification,
    ErrorEvent,
    HookEvent,
    LoopComplete,
    PermissionRequest,
    PermissionResponse,
    RetryEvent,
    StreamText,
    ThinkingText,
    ToolResultEvent,
    ToolUseEvent,
    TurnComplete,
    UsageEvent,
)
from xiaoyi.client import (
    AuthenticationError,
    LLMClient,
    LLMError,
    create_client,
    resolve_context_window,
)
from xiaoyi.commands import (
    CommandContext,
    CommandRegistry,
    complete,
    parse_command,
)
from xiaoyi.commands.completion import CompletionPopup
from xiaoyi.commands.handlers import register_all_commands
from xiaoyi.config import MCPServerConfig, ProviderConfig
from xiaoyi.hooks import HookContext, HookEngine, load_hooks
from xiaoyi.conversation import Attachment, ConversationManager, Message
from xiaoyi.mcp import MCPManager
from xiaoyi.media import image_media_type
from xiaoyi.memory import (
    MemoryManager,
    Session,
    SessionManager,
    find_relevant_memories,
    generate_session_summary,
    load_instructions,
    make_compact_boundary,
    render_reminder,
)
from xiaoyi.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from xiaoyi.agents.loader import AgentLoader
from xiaoyi.agents.task_manager import TaskManager
from xiaoyi.agents.trace import TraceManager
from xiaoyi.agents.notification import inject_task_notifications
from xiaoyi.commands.handlers.tasks import create_tasks_command
from xiaoyi.skills.executor import SkillExecutor
from xiaoyi.skills.loader import SkillLoader
from xiaoyi.commands.handlers.skill_register import register_skill_commands
from rich.text import Text as RichText
from textual.theme import Theme
from xiaoyi.cache import FileCache
from xiaoyi.tools import ToolRegistry, create_default_registry
from xiaoyi.tools.agent_tool import AgentTool
from xiaoyi.tools.ask_user import AskUserEvent, AskUserTool
from xiaoyi.tools.impl.tool_search import ToolSearchTool
from xiaoyi.tools.load_skill import LoadSkill
from xiaoyi.worktree.cleanup import start_stale_cleanup_task
from xiaoyi.worktree.manager import WorktreeManager
from xiaoyi.commands.handlers.worktree import create_worktree_command
from xiaoyi.teammate_tree import TeammateTree

import re

MAX_TRUNCATED_LINES = 20
MAX_AT_REF_BYTES = 10240

_AT_REF_RE = re.compile(r"@([\w./_\-]+(?:\.[\w]+)*)")

_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".xiaoyi", "build", ".gradle"}


def scan_files_for_at(prefix: str, work_dir: str, limit: int = 10) -> list[str]:
    matches: list[str] = []
    base = os.path.join(work_dir, os.path.dirname(prefix)) if "/" in prefix else work_dir
    name_prefix = os.path.basename(prefix).lower()
    if not os.path.isdir(base):
        return matches
    try:
        for entry in sorted(os.listdir(base)):
            if entry in _SKIP_DIRS or entry.startswith("."):
                continue
            if entry.lower().startswith(name_prefix):
                rel = os.path.join(os.path.dirname(prefix), entry) if "/" in prefix else entry
                if os.path.isdir(os.path.join(base, entry)):
                    rel += "/"
                matches.append(rel)
                if len(matches) >= limit:
                    break
    except OSError:
        pass
    return matches


def expand_at_refs(text: str, work_dir: str) -> str:
    def _replace(m: re.Match) -> str:
        rel_path = m.group(1)
        full_path = os.path.join(work_dir, rel_path)
        if not os.path.isfile(full_path):
            return m.group(0)
        try:
            content = open(full_path, encoding="utf-8", errors="replace").read(MAX_AT_REF_BYTES)
            return f"[File: {rel_path}]\n```\n{content}\n```"
        except Exception:
            return m.group(0)
    return _AT_REF_RE.sub(_replace, text)


# 拖拽/粘贴产生的路径形态：裸路径、双引号或单引号包裹。
_INPUT_TOKEN_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'|(\S+)')

# 路径尾部常见的包裹标点（中文标点与引号），提取时先剥离。
_TOKEN_TRIM_CHARS = "，。；：、！？,.;:!?)]}>\"'"


def _normalize_path_token(token: str) -> str:
    """把终端粘贴产生的路径文本还原为本地路径。"""
    path = token.strip().strip(_TOKEN_TRIM_CHARS)
    if path.lower().startswith("file://"):
        path = path[7:]
        # file:///D:/x.png -> D:/x.png；file:///home/x.png 保持 /home/x.png
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
    return os.path.expanduser(path) if path else path


def extract_image_attachments(text: str, work_dir: str) -> tuple[str, list[Attachment]]:
    """从输入文本中提取本地图片路径，转成附件。

    终端不支持传输图片数据：拖拽文件或复制文件后粘贴，实际插入的是该文件的
    路径文本。这里识别其中指向本地图片的路径（裸路径、"..." 包裹、file:// 前缀），
    校验文件确实存在后转为附件，并从文本中移除该路径。

    返回 (剩余文本, 附件列表)。未命中的内容原样保留。
    """
    attachments: list[Attachment] = []
    remove_spans: list[tuple[int, int]] = []

    for m in _INPUT_TOKEN_RE.finditer(text):
        token = m.group(1) or m.group(2) or m.group(3) or ""
        if not token:
            continue
        candidate = _normalize_path_token(token)
        if not candidate:
            continue
        media_type = image_media_type(candidate)
        if media_type is None:
            continue
        local = candidate if os.path.isabs(candidate) else os.path.join(work_dir, candidate)
        if not os.path.isfile(local):
            continue
        attachments.append(Attachment(path=os.path.abspath(local), media_type=media_type))
        start = m.start(1) if m.group(1) else m.start(2) if m.group(2) else m.start(3)
        end = m.end(1) if m.group(1) else m.end(2) if m.group(2) else m.end(3)
        remove_spans.append((start, end))

    if not remove_spans:
        return text, attachments

    remaining = text
    for start, end in reversed(remove_spans):
        remaining = remaining[:start] + remaining[end:]
    # 清理因移除路径产生的多余空白
    remaining = re.sub(r"[ \t]{2,}", " ", remaining).strip()
    return remaining, attachments


class ChatInput(TextArea):
    BINDINGS = [
        Binding("enter", "submit", "Submit", priority=True),
        Binding("shift+enter", "newline", "Newline", priority=True),
        Binding("ctrl+j", "newline", "Newline", priority=True),
        Binding("tab", "complete", "Complete", priority=True),
        Binding("escape", "dismiss_popup", "Dismiss", priority=True),
        Binding("up", "nav_up", "Navigate up", priority=True),
        Binding("down", "nav_down", "Navigate down", priority=True),
        Binding("pageup", "scroll_chat_up", "Scroll chat up", priority=True),
        Binding("pagedown", "scroll_chat_down", "Scroll chat down", priority=True),
        Binding("shift+up", "scroll_chat_line_up", "Scroll up", priority=True),
        Binding("shift+down", "scroll_chat_line_down", "Scroll down", priority=True),
    ]

    class Submitted(TMessage):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class TabComplete(TMessage):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class InterruptRequested(TMessage):
        """请求 App 打断当前回复（ESC 兜底路径）。

        不同 Textual 版本对"App 级 priority 绑定 vs 焦点控件 priority 绑定"
        的裁决顺序不同：若输入框的 escape 绑定先被处理，App 的 cancel
        绑定就收不到按键。这里在弹窗未打开时主动请求打断，保证 ESC
        在任何版本下都能生效。
        """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("placeholder", "输入消息...(输入/唤起快捷指令)")
        super().__init__(**kwargs)
        self.cursor_blink = False
        self._history: list[str] = []
        self._history_index: int = -1
        self._history_draft: str = ""
        self._history_file: Path | None = None

    def load_history(self, work_dir: str) -> None:
        self._history_file = Path(work_dir) / ".xiaoyi" / "history"
        if self._history_file.exists():
            try:
                lines = self._history_file.read_text(encoding="utf-8").splitlines()
                self._history = [l for l in lines if l.strip()]
            except Exception:
                pass

    def _persist_entry(self, text: str) -> None:
        if self._history_file is None:
            return
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._history_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def _popup(self) -> CompletionPopup | None:
        try:
            return self.app.query_one(CompletionPopup)
        except Exception:
            return None

    def action_submit(self) -> None:
        popup = self._popup()
        if popup is not None and popup.is_visible:
            selected = popup.get_selected()
            popup.hide()
            if selected:
                self._history.append(selected)
                self._persist_entry(selected)
                self._history_index = -1
                self._history_draft = ""
                self.post_message(self.Submitted(selected))
                self.clear()
                self.post_message(self.SlashMenuUpdate(None))
                return
        text = self.text.strip()
        if text:
            self._history.append(text)
            self._persist_entry(text)
            self._history_index = -1
            self._history_draft = ""
            self.post_message(self.Submitted(text))
            self.clear()
            self.post_message(self.SlashMenuUpdate(None))

    def action_newline(self) -> None:
        self.insert("\n")

    def action_complete(self) -> None:
        popup = self._popup()
        if popup is not None and popup.is_visible:
            selected = popup.get_selected()
            if selected:
                popup.hide()
                self.clear()
                self.insert(selected + " ")
                # clear()/insert() 不保证触发 Changed，手动同步用法提示行
                self.post_message(self.SlashMenuUpdate(None))
            return
        text = self.text.strip()
        if text.startswith("/"):
            self.post_message(self.TabComplete(text))
        else:
            self.insert("\t")

    def action_dismiss_popup(self) -> None:
        popup = self._popup()
        if popup is not None and popup.is_visible:
            popup.hide()
            return
        # 兜底：输入框先收到 ESC 且无弹窗可关时，请求打断当前回复
        self.post_message(self.InterruptRequested())

    def action_nav_up(self) -> None:
        popup = self._popup()
        if popup is not None and popup.is_visible:
            popup.move_up()
            return
        if not self._history:
            return
        if self._history_index == -1:
            self._history_draft = self.text
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        else:
            return
        self.clear()
        self.insert(self._history[self._history_index])

    def action_nav_down(self) -> None:
        popup = self._popup()
        if popup is not None and popup.is_visible:
            popup.move_down()
            return
        if self._history_index == -1:
            return
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.clear()
            self.insert(self._history[self._history_index])
        else:
            self._history_index = -1
            self.clear()
            self.insert(self._history_draft)

    def action_scroll_chat_up(self) -> None:
        try:
            chat = self.app.query_one("#chat-area", VerticalScroll)
            chat.scroll_page_up(animate=False)
        except Exception:
            pass

    def action_scroll_chat_down(self) -> None:
        try:
            chat = self.app.query_one("#chat-area", VerticalScroll)
            chat.scroll_page_down(animate=False)
        except Exception:
            pass

    def action_scroll_chat_line_up(self) -> None:
        try:
            chat = self.app.query_one("#chat-area", VerticalScroll)
            chat.scroll_up(animate=False)
        except Exception:
            pass

    def action_scroll_chat_line_down(self) -> None:
        try:
            chat = self.app.query_one("#chat-area", VerticalScroll)
            chat.scroll_down(animate=False)
        except Exception:
            pass

    class AtFileRequest(TMessage):
        def __init__(self, prefix: str) -> None:
            super().__init__()
            self.prefix = prefix

    class SlashMenuUpdate(TMessage):
        def __init__(self, prefix: str | None) -> None:
            super().__init__()
            self.prefix = prefix

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        text = self.text
        if text.startswith("/"):
            prefix = text[1:]
            if " " not in prefix and "\n" not in prefix:
                self.post_message(self.SlashMenuUpdate(prefix))
            else:
                self.post_message(self.SlashMenuUpdate(None))
        else:
            self.post_message(self.SlashMenuUpdate(None))

        at_idx = text.rfind("@")
        if at_idx < 0:
            return
        after = text[at_idx + 1:]
        if " " in after or "\n" in after:
            return
        if after:
            self.post_message(self.AtFileRequest(after))


COLLAPSIBLE_TOOLS = {"ReadFile", "Glob", "Grep", "ToolSearch"}


def _is_subagent_tool(tool_name: str) -> bool:
    return tool_name == "Agent"


def _tool_title(tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name == "ReadFile":
        path = os.path.basename(arguments.get("file_path", ""))
        return f"Read {path}" if path else "Read"
    if tool_name == "WriteFile":
        path = os.path.basename(arguments.get("file_path", ""))
        content = arguments.get("content", "")
        lines = content.count("\n") + 1 if content else 0
        return f"Write {path} ({lines} lines)" if path else "Write"
    if tool_name == "EditFile":
        path = os.path.basename(arguments.get("file_path", ""))
        return f"Edit {path}" if path else "Edit"
    if tool_name == "Bash":
        cmd = arguments.get("command", "")
        short = cmd[:50] + "…" if len(cmd) > 50 else cmd
        return f"Bash: {short}" if short else "Bash"
    if tool_name == "Glob":
        return f"Glob: {arguments.get('pattern', '')}"
    if tool_name == "Grep":
        return f"Grep: {arguments.get('pattern', '')}"
    return tool_name


def _format_detail(tool_name: str, arguments: dict[str, Any], output: str) -> str:
    parts: list[str] = []

    if tool_name == "Bash":
        parts.append(f"  IN   {arguments.get('command', '')}")
        parts.append("")
        for line in output.splitlines():
            parts.append(f"  OUT  {line}")
    elif tool_name in ("ReadFile", "WriteFile", "EditFile"):
        parts.append(f"  {arguments.get('file_path', '')}")
        parts.append("")
        for line in output.splitlines()[:MAX_TRUNCATED_LINES]:
            parts.append(f"  {line}")
        total = output.count("\n") + 1
        if total > MAX_TRUNCATED_LINES:
            parts.append(f"  … ({total - MAX_TRUNCATED_LINES} more lines)")
    else:
        for line in output.splitlines()[:MAX_TRUNCATED_LINES]:
            parts.append(f"  {line}")
        total = output.count("\n") + 1
        if total > MAX_TRUNCATED_LINES:
            parts.append(f"  … ({total - MAX_TRUNCATED_LINES} more lines)")

    return "\n".join(parts)


class ToolCallBlock(Static, can_focus=True):

    def __init__(self, tool_name: str, arguments: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self._arguments = arguments
        self._title = _tool_title(tool_name, arguments)
        self._full_output = ""
        self._is_error = False
        self._elapsed = 0.0
        self._collapsed = True
        self._loading = True
        self._render_loading()

    def _render_loading(self) -> None:
        self.update(f"  ● {self._title} …")
        self.add_class("tool-block-loading")

    def set_result(self, output: str, is_error: bool, elapsed: float) -> None:
        self._full_output = output
        self._is_error = is_error
        self._elapsed = elapsed
        self._loading = False
        self._collapsed = True
        self.remove_class("tool-block-loading")
        if is_error:
            self.add_class("tool-block-error")
        self._render_collapsed()

    def _render_collapsed(self) -> None:
        if self._is_error:
            self.update(f"  ✗ {self._title} ({self._elapsed:.1f}s)")
        else:
            self.update(f"  ✓ {self._title} ({self._elapsed:.1f}s)")

    def _render_expanded(self) -> None:
        if self._is_error:
            header = f"  ✗ {self._title} ({self._elapsed:.1f}s)"
        else:
            header = f"  ✓ {self._title} ({self._elapsed:.1f}s)"
        detail = _format_detail(self.tool_name, self._arguments, self._full_output)
        self.update(f"{header}\n{detail}")

    def on_click(self) -> None:
        if self._loading:
            return
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._render_collapsed()
        else:
            self._render_expanded()


_MODE_CYCLE = [
    PermissionMode.DEFAULT,
    PermissionMode.ACCEPT_EDITS,
    PermissionMode.PLAN,
    PermissionMode.BYPASS,
]

_MODE_COLORS = {
    PermissionMode.DEFAULT: "bold #F06538",
    PermissionMode.ACCEPT_EDITS: "bold #4CAF50",
    PermissionMode.PLAN: "bold #FFB74D",
    PermissionMode.BYPASS: "bold #EF5350",
}

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _to_past_tense(verb: str) -> str:
    """把现在进行时动词转换为过去式。"""
    if verb.endswith("ing"):
        stem = verb[:-3]
        if stem.endswith("e"):
            return stem + "d"
        if stem and stem[-1] in "atutitet":
            return stem + "ed"
        return stem + "ed"
    return verb + "ed"


THINKING_VERBS = [
    "Accomplishing", "Architecting", "Baking", "Beboppin'", "Befuddling",
    "Bloviating", "Boogieing", "Boondoggling", "Bootstrapping", "Brewing",
    "Calculating", "Canoodling", "Caramelizing", "Cascading", "Cerebrating",
    "Choreographing", "Churning", "Coalescing", "Cogitating", "Combobulating",
    "Composing", "Computing", "Concocting", "Considering", "Contemplating",
    "Cooking", "Crafting", "Creating", "Crunching", "Crystallizing",
    "Cultivating", "Deciphering", "Deliberating", "Dilly-dallying",
    "Discombobulating", "Doodling", "Elucidating", "Enchanting", "Envisioning",
    "Fermenting", "Finagling", "Flambéing", "Flibbertigibbeting", "Flummoxing",
    "Forging", "Frolicking", "Gallivanting", "Garnishing", "Generating",
    "Germinating", "Grooving", "Harmonizing", "Hatching", "Honking",
    "Hullaballooing", "Ideating", "Imagining", "Improvising", "Incubating",
    "Inferring", "Infusing", "Kneading", "Lollygagging", "Manifesting",
    "Marinating", "Meandering", "Metamorphosing", "Mewing", "Moonwalking",
    "Moseying", "Mulling", "Musing", "Noodling", "Orbiting",
    "Orchestrating", "Percolating", "Philosophising", "Pondering",
    "Pontificating", "Pouncing", "Purring", "Puzzling", "Razzle-dazzling",
    "Ruminating", "Scampering", "Simmering", "Sketching", "Spelunking",
    "Spinning", "Sprouting", "Synthesizing", "Thinking", "Tinkering",
    "Transfiguring", "Transmuting", "Undulating", "Unfurling", "Unravelling",
    "Vibing", "Wandering", "Whisking", "Working", "Wrangling", "Zigzagging",
]  # 共 105 个动词，与 Go 版 internal/tui/verbs.go 完全一致


class ToolGroupSummary(Static, can_focus=True):


    def __init__(self, count: int, total_elapsed: float, **kwargs: Any) -> None:
        label = f"● Done ({count} tool uses · {total_elapsed:.1f}s)  (ctrl+o to expand)"
        super().__init__(label, **kwargs)
        self._count = count
        self._total = total_elapsed
        self._expanded = False

    def _refresh_display(self) -> None:
        if self._expanded:
            self.update(f"▼ Done ({self._count} tool uses · {self._total:.1f}s)")
        else:
            self.update(
                f"● Done ({self._count} tool uses · {self._total:.1f}s)"
                "  (ctrl+o to expand)"
            )

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._refresh_display()


    def on_click(self) -> None:
        self.toggle()


class SubAgentBlock(Static, can_focus=True):

    def __init__(self, agent_type: str, description: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agent_type = agent_type or "agent"
        self._description = description[:60] if description else ""
        self._done = False
        self._is_error = False
        self._elapsed = 0.0
        self._collapsed = True
        self._result_preview = ""
        self._tool_count = 0
        self._render_running()

    def _render_running(self) -> None:
        desc = f"({self._description})" if self._description else ""
        self.update(f"● {self._agent_type}{desc}\n     Running…")

    def set_result(self, output: str, is_error: bool, elapsed: float) -> None:
        self._done = True
        self._is_error = is_error
        self._elapsed = elapsed
        self._result_preview = output[:300] if output else ""
        self._parse_stats(output)
        self._render_done()

    def _parse_stats(self, output: str) -> None:
        import re
        m = re.search(r"(\d+)\s+tool", output[:200])
        if m:
            self._tool_count = int(m.group(1))

    def _render_done(self) -> None:
        desc = f"({self._description})" if self._description else ""
        tool_info = f"{self._tool_count} tool uses · " if self._tool_count else ""
        if self._collapsed:
            self.update(
                f"● {self._agent_type}{desc}\n"
                f"    ⎿  Done ({tool_info}{self._elapsed:.1f}s)  (ctrl+o to expand)"
            )
        else:
            self.update(
                f"● {self._agent_type}{desc}\n"
                f"    ⎿  Done ({tool_info}{self._elapsed:.1f}s)\n"
                f"  {self._result_preview}"
            )

    def on_click(self) -> None:
        if not self._done:
            return
        self._collapsed = not self._collapsed
        self._render_done()


_XIAOYI_THEME = Theme(
    name="xiaoyi",
    primary="#875FFF",
    background="ansi_default",
    surface="ansi_default",
    panel="ansi_default",
    dark=True,
    ansi=True,
)


# Sunset-to-Ocean Gradient directly sampled from Antigravity CLI (img.png)
_IMG_VERTICAL_GRADIENT = [
    "#F2922E",  # Warm Flame Orange (Row 0 apex)
    "#F06538",  # Glowing Sunset Amber (Row 1)
    "#E14F59",  # Deep Coral Rose (Row 2)
    "#9C5B97",  # Orchid Purple (Row 3)
    "#4A80EA",  # Google Royal Blue (Row 4)
    "#64B6F6",  # Celestial Sky Blue (Row 5)
]

# "XiaoYi" FIGlet Standard font (Capital X and Capital Y)
_XIAOYI_LOGO = [
    r"__  ___          __   ___ ",
    r"\ \/ (_) __ _  __\ \ / (_)",
    r" \  /| |/ _` |/ _ \ V /| |",
    r" /  \| | (_| | (_) | | | |",
    r"/_/\_\_|\__,_|\___/|_| |_|",
    r"                          ",
]


class XiaoYiApp(App):
    CSS_PATH = "styles.tcss"
    TITLE = "XiaoYi"
    INLINE_PADDING = 0
    theme = "xiaoyi"
    BINDINGS = [
        Binding("ctrl+c", "handle_ctrl_c", "Quit", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("shift+tab", "cycle_mode", "Cycle mode", priority=True),
        Binding("ctrl+o", "toggle_tool_blocks", "Toggle tools", priority=True),
        Binding("pageup", "scroll_chat_up", "Scroll up", priority=True),
        Binding("pagedown", "scroll_chat_down", "Scroll down", priority=True),
    ]


    def __init__(
        self,
        providers: list[ProviderConfig],
        permission_mode: PermissionMode = PermissionMode.DEFAULT,
        mcp_servers: list[MCPServerConfig] | None = None,
        hook_engine: HookEngine | None = None,
        enable_fork: bool = False,
        enable_verification_agent: bool = False,
        worktree_config: Any = None,
        teammate_mode: str = "",
        enable_coordinator_mode: bool = False,
        driver_class: type | None = None,
    ) -> None:
        super().__init__(driver_class=driver_class)
        self.providers = providers
        self._initial_permission_mode = permission_mode
        self._mcp_server_configs = mcp_servers or []
        self.hook_engine = hook_engine
        self._enable_fork = enable_fork
        self._enable_verification_agent = enable_verification_agent
        self._worktree_config = worktree_config
        self._teammate_mode = teammate_mode
        self._enable_coordinator_mode = enable_coordinator_mode
        self.file_cache = FileCache()
        self.client: LLMClient | None = None
        self.conversation = ConversationManager()
        self.registry: ToolRegistry = create_default_registry(file_cache=self.file_cache)
        self.agent: Agent | None = None
        self.mcp_manager: MCPManager | None = None
        self._mcp_init_task: asyncio.Task[None] | None = None
        self._selected_provider: ProviderConfig | None = None
        self._streaming = False
        self._thinking_start: float = 0.0
        self._thinking_verb: str = ""
        self._spinner_idx: int = 0
        self._spinner_timer = None
        self._spinner_label: Static | None = None
        self._mcp_server_info: str = ""
        self._agent_task: asyncio.Task[None] | None = None
        self._subagent_task: asyncio.Task[None] | None = None
        self._subagent_start_time: float | None = None
        self.session_manager: SessionManager | None = None
        self.session: Session | None = None
        self.memory_manager: MemoryManager | None = None
        self._instructions_content: str = ""
        self.command_registry = CommandRegistry()
        register_all_commands(self.command_registry)
        self.skill_loader: SkillLoader | None = None
        self.skill_executor: SkillExecutor | None = None
        self._load_skill_tool: LoadSkill | None = None
        self.agent_loader: AgentLoader | None = None
        self.task_manager: TaskManager = TaskManager()
        self.trace_manager: TraceManager = TraceManager()
        self._notification_check_task: asyncio.Task[None] | None = None
        self.worktree_manager: WorktreeManager | None = None
        self._stale_cleanup_task: asyncio.Task[None] | None = None
        self._current_streaming_label: Static | None = None
        self._current_ai_row: Vertical | None = None
        self._current_accumulated_text: str = ""
        self._mcp_instructions: str = ""
        self._mcp_instructions_ok: bool = False
        self._mcp_connecting: bool = False
        self._teammate_tree: TeammateTree | None = None
        self._teammate_timer = None

    @staticmethod
    def _make_banner(model: str = "", work_dir: str = "") -> RichText:
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80

        logo_width = 28
        max_right_len = max(24, cols - logo_width - 4)

        model_disp = model if model else "initializing..."
        if len(model_disp) > max_right_len:
            model_disp = model_disp[: max_right_len - 3] + "..."

        cwd_disp = (work_dir if work_dir else os.getcwd()).replace("\\", "/")
        if len(cwd_disp) > max_right_len:
            cwd_disp = "..." + cwd_disp[-(max_right_len - 3) :]

        right_items = [
            ("XiaoYi Agent", "bold #8AB4F8"),
            ("Offered by AI_bu_shi_shou", "bold #8AB4F8"),
            (model_disp, "color(252)"),
            (cwd_disp, "color(242)"),
        ]

        t = RichText()
        for i in range(6):
            logo_line = f"{_XIAOYI_LOGO[i]}    "
            t.append(logo_line, style=f"bold {_IMG_VERTICAL_GRADIENT[i]}")

            if i < len(right_items):
                text, style = right_items[i]
                t.append(text, style=style)
            if i < 5:
                t.append("\n")
        return t

    def compose(self) -> ComposeResult:
        yield Static(self._make_banner(), id="title-bar")

        if len(self.providers) > 1:
            with Vertical(id="provider-select"):
                yield Static("Select a Provider", id="select-label")
                yield OptionList(
                    *[
                        Option(f"{p.name}  [{p.model}]", id=p.name)
                        for p in self.providers
                    ],
                    id="provider-list",
                )
        yield VerticalScroll(id="chat-area")
        with Vertical(id="input-area"):
            yield ChatInput(id="chat-input")
            yield Static("", id="command-hint")
            with Horizontal(id="status-bar"):
                yield Static("[bold #F06538]default[/bold #F06538] [dim]·[/dim] ", id="mode-label")
                yield Static("", id="teammates-label")
                yield Static("", id="model-label")
            yield CompletionPopup()

    def on_mount(self) -> None:
        self.register_theme(_XIAOYI_THEME)
        self.theme = "xiaoyi"
        self.query_one("#command-hint", Static).display = False
        if len(self.providers) == 1:
            self._select_provider(self.providers[0])
        else:
            self.query_one("#chat-area").display = False
            self.query_one("#input-area").display = False

    def _select_provider(self, provider: ProviderConfig) -> None:
        self._selected_provider = provider
        try:
            self.client = create_client(provider)
        except AuthenticationError as e:
            self._show_error(str(e))
            return

        work_dir = os.getcwd()
        home = Path.home()
        checker = PermissionChecker(
            detector=DangerousCommandDetector(),
            sandbox=PathSandbox(work_dir),
            rule_engine=RuleEngine(
                user_rules_path=home / ".xiaoyi" / "permissions.yaml",
                project_rules_path=Path(work_dir) / ".xiaoyi" / "permissions.yaml",
                local_rules_path=Path(work_dir) / ".xiaoyi" / "permissions.local.yaml",
            ),
            mode=self._initial_permission_mode,
        )

        self._instructions_content = load_instructions(work_dir)
        self.memory_manager = MemoryManager(work_dir)
        self.session_manager = SessionManager(work_dir)
        self.session_manager.cleanup()
        self.session = self.session_manager.create()

        from xiaoyi.filehistory import FileHistory
        self.file_history = FileHistory(work_dir, self.session.session_id)
        for tool in self.registry.list_tools():
            if hasattr(tool, "file_history"):
                tool.file_history = self.file_history

        load_skill_tool = LoadSkill()
        self.registry.register(load_skill_tool)
        self._load_skill_tool = load_skill_tool

        self.registry.register(
            ToolSearchTool(self.registry, protocol=provider.protocol)
        )
        self.registry.register(AskUserTool())

        from xiaoyi.tools.exit_plan_mode import ExitPlanModeTool
        self._exit_plan_tool = ExitPlanModeTool()
        self.registry.register(self._exit_plan_tool)

        self.agent = Agent(
            client=self.client,
            registry=self.registry,
            protocol=provider.protocol,
            work_dir=work_dir,
            permission_checker=checker,
            context_window=provider.get_context_window(),
            instructions_content=self._instructions_content,
            memory_manager=self.memory_manager,
            hook_engine=self.hook_engine,
        )
        self.agent.file_history = self.file_history
        self.agent.session_id = self.session.session_id

        self._exit_plan_tool._is_plan_mode = lambda: self.agent.plan_mode
        self._exit_plan_tool._plan_exists = lambda: self.agent._get_plan_path().exists()

        # Layer 2: 在后台异步拉取模型的 context window，不阻塞启动流程。
        # agent 已经有一个同步解析的窗口值（来自配置 / 映射表 / 默认值）；
        # 如果异步拉取成功，就原地升级为更准确的值。
        self.run_worker(
            self._resolve_context_window(provider), exclusive=False
        )

        self.skill_loader = SkillLoader(work_dir)
        self.skill_loader.load_all()

        load_skill_tool.set_loader(self.skill_loader)
        load_skill_tool.set_agent(self.agent)

        self.skill_executor = SkillExecutor(
            agent=self.agent,
            client=self.client,
            protocol=provider.protocol,
        )

        catalog = self.skill_loader.get_catalog()
        if catalog:
            lines = [
                "You can use the following Skills:",
                "",
            ]
            for name, desc in catalog:
                lines.append(f"- {name}: {desc}")
            lines.append("")
            lines.append(
                "If the user's request matches a Skill, call LoadSkill to activate it."
            )
            self.agent.set_skill_catalog("\n".join(lines))

        register_skill_commands(
            self.command_registry, self.skill_loader, self.skill_executor
        )

        # --- Worktree 系统初始化 ---
        from xiaoyi.config import WorktreeConfig
        wt_cfg = self._worktree_config or WorktreeConfig()
        self.worktree_manager = WorktreeManager(
            repo_root=work_dir,
            symlink_directories=wt_cfg.symlink_directories,
        )
        restored = self.worktree_manager.restore_session()
        if restored:
            self.agent.work_dir = restored.worktree_path

        wt_command = create_worktree_command(self.worktree_manager)
        self.command_registry.register_sync(wt_command)

        from xiaoyi.tools.enter_worktree import EnterWorktreeTool
        from xiaoyi.tools.exit_worktree import ExitWorktreeTool
        self.registry.register(EnterWorktreeTool(worktree_manager=self.worktree_manager))
        self.registry.register(ExitWorktreeTool(worktree_manager=self.worktree_manager))

        self._stale_cleanup_task = asyncio.create_task(
            start_stale_cleanup_task(
                self.worktree_manager,
                wt_cfg.stale_cleanup_interval,
                wt_cfg.stale_cutoff_hours,
            )
        )

        # --- 子 agent 系统初始化 ---
        self.agent_loader = AgentLoader(
            work_dir, enable_verification=self._enable_verification_agent
        )
        self.agent_loader.load_all()

        # --- Agent 团队系统初始化 ---
        from xiaoyi.teams.manager import TeamManager
        from xiaoyi.tools.team_create import TeamCreateTool
        from xiaoyi.tools.team_delete import TeamDeleteTool

        self.team_manager = TeamManager(worktree_manager=self.worktree_manager, trace_manager=self.trace_manager)

        agent_tool = AgentTool(
            agent_loader=self.agent_loader,
            task_manager=self.task_manager,
            trace_manager=self.trace_manager,
            parent_agent=self.agent,
            enable_fork=self._enable_fork,
            provider_config=provider,
            worktree_manager=self.worktree_manager,
            team_manager=self.team_manager,
        )
        self.registry.register(agent_tool)

        team_create_tool = TeamCreateTool(
            team_manager=self.team_manager,
            parent_agent=self.agent,
            teammate_mode=self._teammate_mode,
            is_interactive=True,
            enable_coordinator_mode=self._enable_coordinator_mode,
        )
        self.registry.register(team_create_tool)

        team_delete_tool = TeamDeleteTool(
            team_manager=self.team_manager,
            parent_agent=self.agent,
        )
        self.registry.register(team_delete_tool)

        agent_catalog = self.agent_loader.list_agents()
        if agent_catalog:
            lines = [
                "## Available Sub-Agent Types",
                "",
                "Use the Agent tool with subagent_type parameter to delegate tasks:",
                "",
            ]
            for agent_type, when_to_use in agent_catalog:
                lines.append(f"- **{agent_type}**: {when_to_use}")
            if self._enable_fork:
                lines.append("")
                lines.append(
                    "Leave subagent_type empty to fork the current conversation "
                    "(inherits full dialog history)."
                )
            lines.append("")
            lines.append(
                "IMPORTANT: Sub-agents run in the background. "
                "After calling the Agent tool, you will get a task ID immediately. "
                "Do NOT wait, sleep, or poll for the result. "
                "Simply report the task ID to the user and end your turn. "
                "The system will automatically notify when the task completes."
            )
            self.agent.set_agent_catalog("\n".join(lines), catalog_list=agent_catalog)

        tasks_cmd = create_tasks_command(self.task_manager)
        self.command_registry.register_sync(tasks_cmd)

        from xiaoyi.commands.handlers.trace import create_trace_command
        trace_cmd = create_trace_command(self.trace_manager, self.agent.agent_id)
        self.command_registry.register_sync(trace_cmd)

        # --- 协调者模式初始化（工具已注册，激活推迟到 TeamCreate 时） ---
        from xiaoyi.tools.synthetic_output import SyntheticOutputTool

        self.registry.register(SyntheticOutputTool())
        self.agent._team_manager = self.team_manager

        if self.hook_engine:
            asyncio.ensure_future(
                self.hook_engine.run_hooks(
                    "startup", HookContext(event_name="startup")
                )
            )

        if self._mcp_server_configs:
            self._mcp_init_task = asyncio.create_task(self._init_mcp())

        self.query_one("#model-label", Static).update(provider.model)
        work_dir = os.getcwd()
        self.query_one("#title-bar", Static).update(
            self._make_banner(provider.model, work_dir)
        )
        self._update_mode_label()

        select = self.query("#provider-select")
        if select:
            select.first().display = False
        self.query_one("#chat-area").display = True
        self.query_one("#input-area").display = True
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.placeholder = "输入消息...(输入/唤起快捷指令)"
        chat_input.load_history(work_dir)
        chat_input.focus()

        self._notification_check_task = asyncio.create_task(
            self._start_notification_polling()
        )

    async def _resolve_context_window(self, provider: ProviderConfig) -> None:
        """Layer 2 后台 worker：异步拉取模型的 context window，
        拉到就原地升级 agent 的窗口值。

        尽力而为 — resolve_context_window 不会抛异常；如果拉不到，
        agent 继续使用同步解析得到的窗口值。
        """
        await resolve_context_window(provider)
        if self.agent is not None:
            self.agent.context_window = provider.get_context_window()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "provider-list":
            provider = self.providers[event.option_index]
            self._select_provider(provider)

    # -----------------------------------------------------------------
    # UIController 协议实现
    # -----------------------------------------------------------------

    def add_system_message(self, text: str) -> None:
        self._show_system_message(text)

    def send_user_message(self, text: str) -> None:
        if self._streaming or self.agent is None:
            return
        self._agent_task = asyncio.create_task(self._send_message(text))

    def set_plan_mode(self, enabled: bool) -> None:
        if self.agent is None:
            return
        if enabled:
            self._pre_plan_mode = self.agent.permission_mode
            self.agent.set_permission_mode(PermissionMode.PLAN)
        else:
            restore = getattr(self, "_pre_plan_mode", PermissionMode.DEFAULT)
            self.agent.set_permission_mode(restore)
        self._update_mode_label()

    def get_token_count(self) -> tuple[int, int]:
        if self.agent:
            return self.agent.total_input_tokens, self.agent.total_output_tokens
        return 0, 0

    def refresh_status(self) -> None:
        self._update_mode_label()

    # -----------------------------------------------------------------
    # 命令分发
    # -----------------------------------------------------------------


    def _build_command_context(self, args: str) -> CommandContext:
        return CommandContext(
            args=args,
            agent=self.agent,
            conversation=self.conversation,
            session=self.session,
            session_manager=self.session_manager,
            memory_manager=self.memory_manager,
            ui=self,
            config={
                "registry": self.command_registry,
                "set_session": self._set_session,
                "set_conversation": self._set_conversation,
                "clear_chat": self._clear_chat,
                "render_restored": self._render_restored_messages,
                "skill_loader": self.skill_loader,
                "skill_executor": self.skill_executor,
            },
        )

    def _set_session(self, session: Session) -> None:
        self.session = session
        if self.agent:
            self.agent.session_id = session.session_id

    def _persist_compact_boundary(self, notification: CompactNotification) -> None:
        """Layer-2 compact 后写入 compact_boundary 记录。

        将摘要 + 原样保留的尾部内联到一条记录中，resume 时只需这一条
        就能重建压缩后的状态。之前已写入磁盘的原始前缀不会被重放。
        没有活跃 session 或 compact 未产出 boundary 时直接跳过。
        """
        if not self.session or notification.boundary is None:
            return
        record = make_compact_boundary(
            notification.boundary.summary,
            notification.boundary.keep,
        )
        self.session.append_record(record)

    def _set_conversation(self, conv: ConversationManager) -> None:
        self.conversation = conv

    def _clear_chat(self) -> None:
        chat = self.query_one("#chat-area", VerticalScroll)
        chat.remove_children()

    async def _dispatch_command(self, text: str) -> None:
        name, args, is_command = parse_command(text)

        if not is_command:
            if self._streaming or self.agent is None:
                return
            self._agent_task = asyncio.create_task(self._send_message(text))
            return

        if name == "":
            commands = self.command_registry.list_commands()
            lines = ["可用命令："]
            for cmd in commands:
                aliases_str = ", ".join(f"/{a}" for a in cmd.aliases)
                name_part = f"/{cmd.name}"
                if aliases_str:
                    name_part += f", {aliases_str}"
                lines.append(f"  {name_part:<24} {cmd.description}")
            self._show_system_message("\n".join(lines))
            return

        cmd = self.command_registry.find(name)
        if cmd is None:
            self._show_system_message(f"未知命令：/{name}，输入 /help 查看可用命令")
            return

        if not args and cmd.arg_prompt:
            self._show_system_message(cmd.arg_prompt)
            return

        ctx = self._build_command_context(args)
        try:
            await cmd.handler(ctx)
        except Exception as e:
            self._show_error(f"命令执行失败: {e}")

    # -----------------------------------------------------------------
    # 输入处理
    # -----------------------------------------------------------------

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        text = event.text.strip()
        if self._streaming and not text.startswith("/"):
            if self._agent_task and not self._agent_task.done():
                self._agent_task.cancel()
                try:
                    await self._agent_task
                except (asyncio.CancelledError, Exception):
                    pass
            self._finish_streaming()
            self._show_system_message("(response interrupted)")
        await self._dispatch_command(text)

    def on_chat_input_interrupt_requested(
        self, event: ChatInput.InterruptRequested
    ) -> None:
        """ESC 兜底路径：由输入框转发的打断请求，复用 App 的取消逻辑。"""
        self.action_cancel()

    def on_chat_input_tab_complete(self, event: ChatInput.TabComplete) -> None:
        matches = complete(self.command_registry, event.text)
        if not matches:
            return
        popup = self.query_one(CompletionPopup)
        if len(matches) == 1:
            input_widget = self.query_one("#chat-input", ChatInput)
            input_widget.clear()
            input_widget.insert(matches[0][1] + " ")
            self._sync_command_hint()
        else:
            popup.show_pairs(matches)

    def _sync_command_hint(self) -> None:
        """根据输入框首词更新输入框下方的用法提示行。

        输入以 "/" 开头且首词是已注册命令时，显示该命令的 usage；
        其余情况隐藏提示行。每次输入变化都会触发刷新，Tab 补全插入
        命令后（带空格）同样会命中"首词 = 命令"分支。
        """
        hint = None
        cmd = None
        try:
            hint = self.query_one("#command-hint", Static)
            text = self.query_one("#chat-input", ChatInput).text
        except Exception:
            # 应用卸载中（输入框清理会触发文本变化事件）——忽略即可
            return
        if text.startswith("/"):
            rest = text[1:]
            first = rest.split(None, 1)[0].lower() if rest else ""
            cmd = self.command_registry.find(first)
        if cmd is not None and cmd.usage:
            usage = cmd.usage.replace("[", "\\[").replace("]", "\\]")
            hint.update(f"[dim]{usage}[/dim]")
            hint.display = True
        else:
            hint.update("")
            hint.display = False

    def on_chat_input_slash_menu_update(self, event: ChatInput.SlashMenuUpdate) -> None:
        self._sync_command_hint()
        try:
            popup = self.query_one(CompletionPopup)
        except Exception:
            # 应用卸载中——没有弹窗可操作
            return
        if event.prefix is None:
            popup.hide()
            return
        matches = complete(self.command_registry, event.prefix)
        if not matches:
            popup.hide()
            return
        popup.show_pairs(matches)

    def on_chat_input_at_file_request(self, event: ChatInput.AtFileRequest) -> None:
        work_dir = self.agent.work_dir if self.agent else os.getcwd()
        matches = scan_files_for_at(event.prefix, work_dir)
        if matches:
            popup = self.query_one(CompletionPopup)
            popup.show([f"@{m}" for m in matches])

    def on_completion_popup_selected(self, event: CompletionPopup.Selected) -> None:
        input_widget = self.query_one("#chat-input", ChatInput)
        selected = event.value
        text = input_widget.text
        if selected.startswith("@"):
            at_idx = text.rfind("@")
            if at_idx >= 0:
                input_widget.clear()
                input_widget.insert(text[:at_idx] + selected + " ")
                input_widget.focus()
                return
        input_widget.clear()
        input_widget.insert(selected + " ")
        input_widget.focus()

    def action_cycle_mode(self) -> None:
        if self.agent is None:
            return
        current = self.agent.permission_mode
        try:
            idx = _MODE_CYCLE.index(current)
        except ValueError:
            idx = 0
        next_mode = _MODE_CYCLE[(idx + 1) % len(_MODE_CYCLE)]
        self.agent.set_permission_mode(next_mode)
        self._update_mode_label()

    def action_toggle_tool_blocks(self) -> None:
        for block in self.query(ToolCallBlock):
            if block._loading:
                continue
            block._collapsed = not block._collapsed
            if block._collapsed:
                block._render_collapsed()
            else:
                block._render_expanded()

        for summary in self.query(ToolGroupSummary):
            was_expanded = summary._expanded
            summary.toggle()
            parent = summary.parent
            if parent:
                for child in parent.children:
                    if isinstance(child, ToolCallBlock) and child.tool_name in COLLAPSIBLE_TOOLS:
                        child.display = summary._expanded

        for block in self.query(SubAgentBlock):
            if block._done:
                block._collapsed = not block._collapsed
                block._render_done()

    def action_cancel(self) -> None:
        popup = self.query_one(CompletionPopup)
        if popup.is_visible:
            popup.hide()
            self.query_one("#chat-input", ChatInput).focus()
            return
        if self._agent_task and not self._agent_task.done():
            if self._subagent_task and not self._subagent_task.done():
                task_id = self.task_manager.adopt_running(
                    self._subagent_task, "background task"
                ) if hasattr(self.task_manager, 'adopt_running') else None
                if task_id:
                    self._show_system_message(
                        f"Task moved to background (id: {task_id})"
                    )
                    return
            self._agent_task.cancel()

    async def _prefetch_relevant_memories(self, query: str) -> str:
        """Run the recall selector as a side-query with an 8s timeout.

        Creates a fresh LLM client so the selector's system prompt is
        independent of the main conversation's system prompt. Returns the
        rendered system-reminder body, or "" on any failure / timeout.
        """
        if self.memory_manager is None or self._selected_provider is None:
            return ""

        provider = self._selected_provider
        user_dir = self.memory_manager.user_mem_dir
        project_dir = self.memory_manager.project_mem_dir

        async def selector(system_prompt: str, user_message: str) -> str:
            from xiaoyi.tools.base import StreamEnd, TextDelta

            side_client = create_client(provider)
            mini_conv = ConversationManager()
            mini_conv.history = [Message(role="user", content=user_message)]
            collected = ""
            async for event in side_client.stream(mini_conv, system=system_prompt):
                if isinstance(event, TextDelta):
                    collected += event.text
                elif isinstance(event, StreamEnd):
                    pass
            return collected

        try:
            results = await asyncio.wait_for(
                find_relevant_memories(
                    query=query,
                    user_mem_dir=user_dir,
                    project_mem_dir=project_dir,
                    recent_tools=None,
                    already_surfaced=None,
                    selector=selector,
                ),
                timeout=8.0,
            )
            return render_reminder(results)
        except (asyncio.TimeoutError, Exception):
            return ""

    async def _send_message(self, text: str, is_notification: bool = False) -> None:
        assert self.agent is not None

        if self._mcp_init_task and not self._mcp_init_task.done():
            self._show_system_message("Waiting for MCP servers to connect...")
            await self._mcp_init_task

        self._streaming = True
        chat = self.query_one("#chat-area", VerticalScroll)
        input_widget = self.query_one("#chat-input", ChatInput)

        if text and "@" in text:
            text = expand_at_refs(text, self.agent.work_dir)

        # Start memory recall prefetch before UI work.
        prefetch_task = asyncio.create_task(
            self._prefetch_relevant_memories(text)
        ) if text else None

        # 拖拽/粘贴图片得到的是路径文本；识别为附件后从正文中移除。
        attachments: list[Attachment] = []
        if text:
            text, attachments = extract_image_attachments(text, self.agent.work_dir)

        if text or attachments:
            user_row = Vertical(classes="user-row")
            await chat.mount(user_row)
            from rich.text import Text as RichText
            user_rich = RichText()
            user_rich.append("❯ ", style="bold color(80)")
            if text:
                user_rich.append(text, style="bold color(255)")
            for att in attachments:
                user_rich.append("\n  ", style="bold color(255)")
                user_rich.append(
                    f"[图片] {os.path.basename(att.path)}",
                    style="bold color(110)",
                )
            user_bubble = Static(user_rich, classes="message user-message")
            await user_row.mount(user_bubble)
            self.call_after_refresh(chat.scroll_end, animate=False)

            self.conversation.add_user_message(text, attachments=attachments)
            if self.session:
                self.session.append(
                    Message(role="user", content=text, attachments=attachments)
                )

            if attachments and not getattr(self._selected_provider, "vision", False):
                names = "、".join(os.path.basename(a.path) for a in attachments)
                self._show_system_message(
                    f"提示：图片 {names} 已附加，但当前 provider 未启用视觉"
                    "（config.yaml 中设置 vision: true 或改用支持视觉的模型），"
                    "图片不会随请求发送。"
                )

        if self._mcp_instructions and not self._mcp_instructions_ok:
            self.conversation.add_system_reminder(self._mcp_instructions)
            self._mcp_instructions_ok = True

        # Collect prefetched recall with 3s timeout, inject as system-reminder.
        if prefetch_task is not None:
            try:
                reminder = await asyncio.wait_for(prefetch_task, timeout=3.0)
                if reminder:
                    self.conversation.add_system_reminder(reminder)
            except (asyncio.TimeoutError, Exception):
                pass

        history_cursor = len(self.conversation.history)

        # 准备 AI 回复区域
        ai_row = Vertical(classes="ai-row")
        await chat.mount(ai_row)
        streaming_label = Static("", classes="message ai-message")
        await ai_row.mount(streaming_label)

        accumulated_text = ""
        tool_blocks: dict[str, ToolCallBlock] = {}

        # 在聊天区底部启动持续旋转的加载动画
        self._thinking_start = _time.monotonic()
        self._thinking_verb = random.choice(THINKING_VERBS)
        self._spinner_idx = 0
        self._spinner_label = Static(
            f"  {SPINNER_FRAMES[0]} {self._thinking_verb}…  · Esc 打断",
            id="spinner-live",
        )
        await chat.mount(self._spinner_label)

        # Mount teammate tree (initially hidden) below the spinner
        self._teammate_tree = TeammateTree(id="teammate-tree")
        self._teammate_tree.display = False
        await chat.mount(self._teammate_tree)
        self._start_teammate_polling()

        self.call_after_refresh(chat.scroll_end, animate=False)
        self._start_spinner()

        await asyncio.sleep(0)

        try:
            async for event in self.agent.run(self.conversation):
                if isinstance(event, ThinkingText):
                    self.call_after_refresh(chat.scroll_end, animate=False)

                elif isinstance(event, StreamText):
                    if streaming_label is not None and not accumulated_text:
                        await streaming_label.remove()
                        streaming_label = Static("", classes="message ai-message")
                        await ai_row.mount(streaming_label)
                    accumulated_text += event.text
                    from rich.text import Text as RichText
                    t = RichText()
                    t.append("● ", style="bold color(99)")
                    t.append(accumulated_text)
                    streaming_label.update(t)
                    self.call_after_refresh(chat.scroll_end, animate=False)

                elif isinstance(event, RetryEvent):
                    self._show_system_message(f"↻ Retrying: {event.reason}")

                elif isinstance(event, ToolUseEvent):
                    if accumulated_text:
                        if streaming_label is not None:
                            await streaming_label.remove()
                        from rich.text import Text as RichText
                        prefix = Static(RichText("●  ", style="bold color(99)"), classes="message")
                        await ai_row.mount(prefix)
                        md = Markdown(accumulated_text, classes="message ai-message")
                        await ai_row.mount(md)
                        streaming_label = None
                        accumulated_text = ""
                    elif streaming_label is not None:
                        await streaming_label.remove()
                        streaming_label = None

                    if _is_subagent_tool(event.tool_name):
                        agent_type = event.arguments.get("subagent_type", "")
                        desc = event.arguments.get("description", "")
                        block = SubAgentBlock(
                            agent_type or "agent",
                            desc,
                            classes="tool-block subagent-block",
                        )
                    else:
                        block = ToolCallBlock(
                            event.tool_name, event.arguments, classes="tool-block"
                        )
                    await ai_row.mount(block)
                    tool_blocks[event.tool_id] = block
                    self.call_after_refresh(chat.scroll_end, animate=False)

                elif isinstance(event, PermissionRequest):
                    await self._handle_permission_request(event)

                elif isinstance(event, ToolResultEvent):
                    block = tool_blocks.get(event.tool_id)
                    if block:
                        block.set_result(event.output, event.is_error, event.elapsed)
                    self.call_after_refresh(chat.scroll_end, animate=False)

                    ask_tool = self.registry.get("AskUserQuestion")
                    if ask_tool and isinstance(ask_tool, AskUserTool) and ask_tool._pending_event:
                        await self._handle_askuser(ask_tool._pending_event)

                elif isinstance(event, TurnComplete):
                    if self.session:
                        for msg in self.conversation.history[history_cursor:]:
                            self.session.append(msg)
                        history_cursor = len(self.conversation.history)

                    collapsible = [
                        (tid, blk) for tid, blk in tool_blocks.items()
                        if isinstance(blk, ToolCallBlock)
                        and blk.tool_name in COLLAPSIBLE_TOOLS
                        and not blk._loading
                    ]
                    if len(collapsible) >= 2:
                        total_elapsed = sum(b._elapsed for _, b in collapsible)
                        summary = ToolGroupSummary(
                            len(collapsible), total_elapsed,
                            classes="tool-block tool-group-summary",
                        )
                        for _, blk in collapsible:
                            blk.display = False
                        await ai_row.mount(summary)

                    tool_blocks.clear()
                    ai_row = Vertical(classes="ai-row")
                    await chat.mount(ai_row)
                    streaming_label = Static("", classes="message ai-message")
                    await ai_row.mount(streaming_label)
                    accumulated_text = ""
                    self.call_after_refresh(chat.scroll_end, animate=False)

                elif isinstance(event, UsageEvent):
                    pass  # token 展示已移除

                elif isinstance(event, HookEvent):
                    status = "✓" if event.success else "✗"
                    self._show_system_message(
                        f"Hook [{event.hook_id}] {status} {event.output}"
                    )

                elif isinstance(event, CompactNotification):
                    self._show_system_message(event.message)
                    # auto_compact 已重写 conversation.history（摘要 +
                    # boundary + 保留尾部）。先持久化 boundary 记录，然后
                    # 将游标推进到重建后的历史末尾，这样 TurnComplete/LoopComplete
                    # 刷盘时只追加 boundary 之后的新消息，不会把已压缩的
                    # 前缀作为普通记录重复写入。
                    self._persist_compact_boundary(event)
                    history_cursor = len(self.conversation.history)

                elif isinstance(event, ErrorEvent):
                    self._show_error(event.message)

                elif isinstance(event, LoopComplete):
                    total_time = _time.monotonic() - self._thinking_start
                    done_label = Static(
                        f"✻ {_to_past_tense(self._thinking_verb)} for {total_time:.1f}s",
                        classes="message thinking-done",
                    )
                    await ai_row.mount(done_label)
                    if self.session:
                        for msg in self.conversation.history[history_cursor:]:
                            self.session.append(msg)
                        history_cursor = len(self.conversation.history)
                        self.session.meta.total_tokens = (
                            self.agent.total_input_tokens
                            + self.agent.total_output_tokens
                        )
                        asyncio.ensure_future(
                            self._update_session_summary()
                        )
                    if self.agent.plan_mode:
                        asyncio.ensure_future(
                            self._show_plan_approval()
                        )

            # 收尾：渲染剩余的累积文本
            if accumulated_text and streaming_label is not None:
                await streaming_label.remove()
                md = Markdown(accumulated_text, classes="message ai-message")
                await ai_row.mount(md)
            elif streaming_label is not None:
                await streaming_label.remove()

            self.call_after_refresh(chat.scroll_end, animate=False)

        except asyncio.CancelledError:
            if accumulated_text:
                if streaming_label is not None:
                    await streaming_label.remove()
                md = Markdown(
                    accumulated_text + "\n\n*[cancelled]*",
                    classes="message ai-message",
                )
                await ai_row.mount(md)
            self._show_system_message("Operation cancelled")
        except LLMError as e:
            self._show_error(str(e))
        finally:
            self._finish_streaming()
            input_widget.focus()

            await self._process_task_notifications()

    async def _process_task_notifications(self) -> None:
        completed = self.task_manager.poll_completed()
        if not completed or self.agent is None:
            return

        inject_task_notifications(self.conversation, completed)

        for task in completed:
            status_icon = "✓" if task.status == "completed" else "✗"
            self._show_system_message(
                f"{status_icon} 后台任务完成: [{task.id}] {task.name} — {task.status}"
            )

            if hasattr(self, 'team_manager'):
                self.team_manager.on_teammate_completed(task.agent.agent_id)

        self._agent_task = asyncio.create_task(
            self._send_message("", is_notification=True)
        )

    async def _start_notification_polling(self) -> None:
        while True:
            await asyncio.sleep(2)
            if not self._streaming and self.agent is not None:
                await self._process_task_notifications()
                await self._process_mailbox_notifications()

    async def _process_mailbox_notifications(self) -> None:
        if not hasattr(self, "team_manager") or self.team_manager is None:
            return
        if self._streaming or self.agent is None:
            return
        notes = self.team_manager.drain_lead_mailbox()
        if not notes:
            return
        for note in notes:
            self.conversation.add_system_reminder(note)
        self._agent_task = asyncio.create_task(
            self._send_message("", is_notification=True)
        )

    async def _show_plan_approval(self) -> None:
        from xiaoyi.plan_dialog import InlinePlanWidget

        chat = self.query_one("#chat-area", VerticalScroll)
        widget = InlinePlanWidget()
        await chat.mount(widget)
        self.call_after_refresh(chat.scroll_end, animate=False)
        try:
            self.query_one("#chat-input").disabled = True
        except Exception:
            pass

    def on_inline_plan_widget_responded(
        self, event: "InlinePlanWidget.Responded"
    ) -> None:
        from xiaoyi.plan_dialog import InlinePlanWidget, PlanChoice

        try:
            self.query_one("#plan-inline", InlinePlanWidget).remove()
        except Exception:
            pass
        try:
            self.query_one("#chat-input").disabled = False
            self.query_one("#chat-input").focus()
        except Exception:
            pass

        if self.agent is None:
            return

        choice = event.choice
        feedback = event.feedback
        plan_path = self.agent._get_plan_path()
        plan_content = ""
        if plan_path.exists():
            try:
                plan_content = plan_path.read_text(encoding="utf-8")
            except Exception:
                pass

        pre = getattr(self, "_pre_plan_mode", PermissionMode.DEFAULT)
        if choice == PlanChoice.YOLO:
            self.agent.set_permission_mode(PermissionMode.BYPASS)
            self._update_mode_label()
            if plan_content:
                self.send_user_message(f"Execute this plan:\n\n{plan_content}")
        elif choice == PlanChoice.MANUAL:
            self.agent.set_permission_mode(pre)
            self._update_mode_label()
            if plan_content:
                self.send_user_message(f"Execute this plan:\n\n{plan_content}")
        elif choice == PlanChoice.FEEDBACK:
            if feedback:
                self.send_user_message(feedback)
            else:
                self._show_system_message("Type your feedback and send.")

    async def _handle_askuser(self, event: AskUserEvent) -> None:
        from xiaoyi.askuser_dialog import InlineAskUserWidget

        chat = self.query_one("#chat-area", VerticalScroll)
        widget = InlineAskUserWidget(event.questions)
        self._pending_askuser_event = event
        await chat.mount(widget)
        self.call_after_refresh(chat.scroll_end, animate=False)
        try:
            self.query_one("#chat-input").disabled = True
        except Exception:
            pass

    def on_inline_ask_user_widget_responded(
        self, event: "InlineAskUserWidget.Responded"
    ) -> None:
        from xiaoyi.askuser_dialog import InlineAskUserWidget

        req = getattr(self, "_pending_askuser_event", None)
        if req is not None and not req.future.done():
            req.future.set_result(event.answers if event.answers else {})
            self._pending_askuser_event = None
        try:
            self.query_one("#askuser-inline", InlineAskUserWidget).remove()
        except Exception:
            pass
        try:
            self.query_one("#chat-input").disabled = False
            self.query_one("#chat-input").focus()
        except Exception:
            pass

    def _start_spinner(self) -> None:
        """启动 braille spinner 动画（每帧 80ms）。"""
        if self._spinner_timer is not None:
            return
        self._spinner_timer = self.set_interval(0.08, self._tick_spinner)

    def _stop_spinner(self) -> None:
        """停止 spinner 动画。"""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _finish_streaming(self) -> None:
        """清理所有 streaming 状态（取消或完成时调用）。"""
        self._streaming = False
        self._stop_spinner()
        self._stop_teammate_polling()
        self._agent_task = None
        if self._teammate_tree is not None:
            self._teammate_tree.remove()
            self._teammate_tree = None
        if self._spinner_label is not None:
            self._spinner_label.remove()
            self._spinner_label = None
        self._clear_pending_interactions()

    def _clear_pending_interactions(self) -> None:
        """清理未决的内联交互（权限确认 / 询问用户）。

        ESC 打断时，等待中的 future 会随任务取消，但挂载在聊天区的
        内联弹窗会残留，且输入框处于禁用状态。这里统一移除残留组件、
        取消未决 future 并恢复输入框，避免出现可点击但已失效的弹窗。
        """
        for attr in ("_pending_perm_request", "_pending_askuser_event"):
            req = getattr(self, attr, None)
            if req is not None:
                future = getattr(req, "future", None)
                if future is not None and not future.done():
                    future.cancel()
            setattr(self, attr, None)
        for selector in ("#perm-inline", "#askuser-inline"):
            try:
                self.query_one(selector).remove()
            except Exception:
                pass
        try:
            inp = self.query_one("#chat-input", ChatInput)
            inp.disabled = False
            inp.focus()
        except Exception:
            pass

    def _tick_spinner(self) -> None:
        """推进持久 spinner 标签上的动画帧。"""
        self._spinner_idx += 1
        frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
        elapsed = _time.monotonic() - self._thinking_start
        if self._spinner_label is not None:
            self._spinner_label.update(
                f"  {frame} {self._thinking_verb}…  ({elapsed:.0f}s)  · Esc 打断"
            )
            if self._spinner_idx % 5 == 0:
                try:
                    self.query_one("#chat-area", VerticalScroll).scroll_end(animate=False)
                except Exception:
                    pass

    def _start_teammate_polling(self) -> None:
        """Start polling teammate progress every 0.5s."""
        if self._teammate_timer is not None:
            return
        self._teammate_timer = self.set_interval(0.5, self._tick_teammate_tree)

    def _stop_teammate_polling(self) -> None:
        """Stop the teammate progress polling timer."""
        if self._teammate_timer is not None:
            self._teammate_timer.stop()
            self._teammate_timer = None

    def _tick_teammate_tree(self) -> None:
        """Poll team_manager for teammate progress and update the tree widget."""
        if not hasattr(self, "team_manager") or self.team_manager is None:
            return
        if self._teammate_tree is None:
            return

        progress_list = self.team_manager.get_all_teammate_progress()

        if not progress_list:
            self._teammate_tree.display = False
            self._update_teammates_label(0)
            return

        # Update the reactive properties via mutate_reactive for list
        self._teammate_tree.teammates = list(progress_list)

        # Update leader tokens from main agent
        if self.agent:
            self._teammate_tree.leader_tokens = (
                self.agent.total_input_tokens + self.agent.total_output_tokens
            )

        self._teammate_tree.display = True
        active_count = sum(1 for p in progress_list if p.status == "running")
        self._update_teammates_label(active_count)

    def _update_teammates_label(self, count: int) -> None:
        """Update the teammates count in the status bar."""
        try:
            label = self.query_one("#teammates-label", Static)
            if count > 0:
                label.update(f"[cyan]● {count} teammate{'s' if count != 1 else ''}[/cyan]  ")
            else:
                label.update("")
        except Exception:
            pass

    async def _handle_permission_request(self, request: PermissionRequest) -> None:
        from xiaoyi.permission_dialog import InlinePermissionWidget

        chat = self.query_one("#chat-area", VerticalScroll)
        widget = InlinePermissionWidget(request.tool_name, request.description)
        self._pending_perm_request = request
        await chat.mount(widget)
        self.call_after_refresh(chat.scroll_end, animate=False)
        # 权限提示弹窗期间禁用输入框
        try:
            self.query_one("#chat-input").disabled = True
        except Exception:
            pass

    def on_inline_permission_widget_responded(
        self, event: "InlinePermissionWidget.Responded"
    ) -> None:
        from xiaoyi.permission_dialog import InlinePermissionWidget

        req = getattr(self, "_pending_perm_request", None)
        if req is not None and not req.future.done():
            req.future.set_result(event.response)
        # 无论 future 是否已被打断取消，都视为该请求已结束
        self._pending_perm_request = None
        # 从聊天区移除权限弹窗组件
        try:
            widget = self.query_one("#perm-inline", InlinePermissionWidget)
            widget.remove()
        except Exception:
            pass
        # 重新启用输入框
        try:
            self.query_one("#chat-input").disabled = False
            self.query_one("#chat-input").focus()
        except Exception:
            pass

    # -----------------------------------------------------------------
    # 恢复 session 的消息渲染
    # -----------------------------------------------------------------

    async def _render_restored_messages(self, messages: list[Message]) -> None:
        chat = self.query_one("#chat-area", VerticalScroll)
        await chat.remove_children()

        for msg in messages:
            if msg.tool_results or not msg.content:
                continue
            if msg.role == "user":
                row = Vertical(classes="user-row")
                await chat.mount(row)
                user_rich = RichText()
                user_rich.append("❯ ", style="bold color(80)")
                user_rich.append(msg.content, style="bold color(255)")
                for att in msg.attachments:
                    user_rich.append("\n  ", style="bold color(255)")
                    user_rich.append(
                        f"[图片] {os.path.basename(att.path)}",
                        style="bold color(110)",
                    )
                bubble = Static(user_rich, classes="message user-message")
                await row.mount(bubble)
            elif msg.role == "assistant":
                row = Vertical(classes="ai-row")
                await chat.mount(row)
                md = Markdown(msg.content, classes="message ai-message")
                await row.mount(md)

        self.call_after_refresh(chat.scroll_end, animate=False)

    # -----------------------------------------------------------------
    # Session 摘要（异步后台生成）
    # -----------------------------------------------------------------

    async def _update_session_summary(self) -> None:
        if not self.session or not self.client or not self.agent:
            return
        try:
            summary = await generate_session_summary(
                self.client, self.conversation, self.agent.protocol
            )
            if summary:
                self.session.meta.summary = summary
                self.session.meta.save(
                    self.session._sessions_dir / f"{self.session.session_id}.meta"
                )
        except Exception:
            pass

    # -----------------------------------------------------------------
    # MCP
    # -----------------------------------------------------------------

    async def _init_mcp(self) -> None:
        self._mcp_connecting = True
        self._update_mode_label()
        manager = MCPManager()
        manager.load_configs(self._mcp_server_configs)
        tools_before = len(self.registry.list_tools())
        errors = await manager.register_all_tools(self.registry)
        self.mcp_manager = manager
        self._mcp_connecting = False
        self._update_mode_label()
        for err in errors:
            self._show_system_message(f"MCP warning: {err}")
        tools_after = len(self.registry.list_tools())
        mcp_tools = tools_after - tools_before
        server_count = len(manager._clients)
        if server_count > 0:
            self._mcp_server_info = (
                f"Connected to {server_count} MCP server(s), {mcp_tools} tools registered"
            )
        if server_count > 0 and mcp_tools > 0:
            parts = []
            for cfg in self._mcp_server_configs:
                srv_name = cfg.name if hasattr(cfg, 'name') else str(cfg)
                tool_names = [
                    t.name for t in self.registry.list_tools()
                    if t.name.startswith(f"mcp__{srv_name}__")
                ]
                section = f"## {srv_name}\n"
                if tool_names:
                    section += "Available tools: " + ", ".join(tool_names)
                parts.append(section)
            self._mcp_instructions = (
                "# MCP Server Instructions\n\n"
                "The following MCP servers are connected. "
                "Use their tools when the user asks.\n\n"
                + "\n\n".join(parts)
            )

    async def _shutdown_mcp(self) -> None:
        if self._mcp_init_task is not None:
            self._mcp_init_task.cancel()
            try:
                await self._mcp_init_task
            except (asyncio.CancelledError, Exception):
                pass
            self._mcp_init_task = None
        if self.mcp_manager is not None:
            await self.mcp_manager.shutdown()
            self.mcp_manager = None

    # -----------------------------------------------------------------
    # 滚动
    # -----------------------------------------------------------------

    def action_scroll_chat_up(self) -> None:
        try:
            chat = self.query_one("#chat-area", VerticalScroll)
            chat.scroll_page_up(animate=False)
        except Exception:
            pass

    def action_scroll_chat_down(self) -> None:
        try:
            chat = self.query_one("#chat-area", VerticalScroll)
            chat.scroll_page_down(animate=False)
        except Exception:
            pass

    # -----------------------------------------------------------------
    # 退出
    # -----------------------------------------------------------------

    async def _graceful_shutdown(self) -> None:
        """退出前的资源清理（Ctrl+C 与 /exit 共用）。"""
        tasks: list[asyncio.Task] = []

        if self.agent and self.agent.memory_manager:
            tasks.append(asyncio.create_task(
                self.agent._extract_memories(self.conversation)
            ))
        if self.hook_engine:
            tasks.append(asyncio.create_task(
                self.hook_engine.run_hooks(
                    "shutdown", HookContext(event_name="shutdown")
                )
            ))
        tasks.append(asyncio.create_task(self._shutdown_mcp()))

        if tasks:
            await asyncio.wait(tasks, timeout=3.0)
            for t in tasks:
                if not t.done():
                    t.cancel()

        if self._stale_cleanup_task and not self._stale_cleanup_task.done():
            self._stale_cleanup_task.cancel()
        if self._notification_check_task and not self._notification_check_task.done():
            self._notification_check_task.cancel()

        if hasattr(self, 'team_manager'):
            for name in list(self.team_manager._teams):
                try:
                    team = self.team_manager._teams[name]
                    for m in team.members:
                        team.set_member_active(m.name, False)
                    self.team_manager.delete_team(name)
                except Exception:
                    pass

        if self.session:
            self.session.close()

    async def request_exit(self) -> None:
        """优雅退出入口（/exit 与 Ctrl+C 共用）。

        进行中的回复先打断，然后清理资源（记忆抽取、shutdown hooks、
        MCP 连接、后台任务、团队、会话），最后退出应用。
        """
        if self._streaming:
            if self._agent_task and not self._agent_task.done():
                self._agent_task.cancel()
            self._finish_streaming()
        try:
            await self._graceful_shutdown()
        except Exception:
            pass
        self.exit()

    async def action_handle_ctrl_c(self) -> None:
        if self._streaming:
            if self._agent_task and not self._agent_task.done():
                self._agent_task.cancel()
            self._show_system_message("(response interrupted)")
            self._finish_streaming()
            try:
                inp = self.query_one("#chat-input", ChatInput)
                inp.disabled = False
                inp.focus()
            except Exception:
                pass
            return

        # 空闲时 Ctrl+C：与 /exit 相同的优雅退出
        await self.request_exit()

    def _show_error(self, text: str) -> None:
        try:
            chat = self.query_one("#chat-area", VerticalScroll)
        except Exception:
            # 应用卸载中（例如退出时取消任务的收尾消息）——没有聊天区可写
            return
        error_widget = Static(f"✖ {text}", classes="message error-message")
        chat.mount(error_widget)
        self.call_after_refresh(chat.scroll_end, animate=False)

    def _show_system_message(self, text: str) -> None:
        try:
            chat = self.query_one("#chat-area", VerticalScroll)
        except Exception:
            # 应用卸载中（例如退出时取消任务的收尾消息）——没有聊天区可写
            return
        msg = Static(f"  {text}", classes="message system-message")
        chat.mount(msg)
        self.call_after_refresh(chat.scroll_end, animate=False)

    _MODE_DISPLAY = {
        PermissionMode.DEFAULT: "default",
        PermissionMode.ACCEPT_EDITS: "accept-edits",
        PermissionMode.PLAN: "plan",
        PermissionMode.BYPASS: "YOLO",
    }

    def _update_mode_label(self) -> None:
        if self.agent:
            perm = self.agent.permission_mode
            display = self._MODE_DISPLAY.get(perm, perm.value)
            color = _MODE_COLORS.get(perm, "bold #F06538")
            label = self.query_one("#mode-label", Static)
            if perm == PermissionMode.DEFAULT:
                label.update(f"[{color}]{display}[/{color}] [dim]·[/dim] ")
            else:
                label.update(f"[{color}]{display}[/{color}] [dim](shift+tab to cycle) ·[/dim] ")
        else:
            try:
                label = self.query_one("#mode-label", Static)
                label.update(f"[bold #F06538]default[/bold #F06538] [dim]·[/dim] ")
            except Exception:
                pass
        try:
            model_label = self.query_one("#model-label", Static)
            model_text = self._selected_provider.model if self._selected_provider else ""
            if self._mcp_connecting:
                model_label.update(f"[yellow]MCP connecting…[/yellow]  [#E0E0E0]{model_text}[/#E0E0E0]")
            else:
                model_label.update(f"[#E0E0E0]{model_text}[/#E0E0E0]")
        except Exception:
            pass

    def _update_token_label(self, input_tokens: int, output_tokens: int) -> None:
        pass  # token 标签已从 UI 中移除
