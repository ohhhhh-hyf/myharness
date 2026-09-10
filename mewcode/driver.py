# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    from textual.drivers.windows_driver import WindowsDriver as _BaseDriver
else:
    from textual.drivers.linux_driver import LinuxDriver as _BaseDriver


class NoAltScreenDriver(_BaseDriver):
    """跳过备用屏（alternate screen）的 driver，让输出保留在主终端的
    滚动回看（scrollback）区域中——与 Claude Code 的渲染行为保持一致。
    自动根据平台选择 LinuxDriver 或 WindowsDriver 作为基类。

    原理：去掉 alt screen 切换码，并在进入应用模式时输出足够多的空行，
    将已有终端内容推入 scrollback，Textual 在"新页面"上渲染。"""

    def start_application_mode(self):
        try:
            rows = os.get_terminal_size().lines
        except OSError:
            rows = 24
        # 在 Textual 接管终端之前，用换行把已有内容推入 scrollback
        sys.stdout.write("\n" * rows)
        sys.stdout.flush()
        super().start_application_mode()

    def write(self, data: str) -> None:
        if "\x1b[?1049h" in data:
            data = data.replace("\x1b[?1049h", "")
        if "\x1b[?1049l" in data:
            data = data.replace("\x1b[?1049l", "")
        if data:
            super().write(data)

    def stop_application_mode(self) -> None:
        """退出应用模式，并擦除本驱动留在屏幕上的最后一帧。

        Textual 原生依赖"离开备用屏"（\\x1b[?1049l）把应用画面切走；本驱动
        为了让内容留在 scrollback 里剥掉了这个序列，因此退出时输入框/状态栏
        会残留在屏幕上，和 shell 提示符交错。这里在 Textual 完成收尾后，
        主动擦除输入区所在行及其下方内容，只保留上方的对话历史。
        """
        super().stop_application_mode()
        _erase_app_frame(self)


def _erase_app_frame(driver) -> None:
    """擦除应用占用的底部区域（输入框 + 状态栏）。

    起点取输入区的实际位置（`#input-area` 的屏内行号 + 1，转成 1-based
    终端行号）；取不到时退化为"从当前光标处清到屏幕末尾"。所有写入都在
    try/except 中，退出路径绝不能因此抛出异常。
    """
    clear_from: int | None = None
    try:
        area = driver._app.screen.query_one("#input-area")
        region = area.region
        if area.display and region.height > 0:
            clear_from = region.y + 1
    except Exception:
        clear_from = None

    try:
        if clear_from is None:
            driver.write("\r")
        else:
            driver.write(f"\x1b[{clear_from};1H")
        driver.write("\x1b[0m")     # 关闭残留样式
        driver.write("\x1b[J")      # 清除光标以下所有内容（输入框/状态栏）
        driver.write("\x1b[?25h")   # 确保光标可见
        driver.flush()
    except Exception:
        pass
