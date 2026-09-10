
from __future__ import annotations

from xiaoyi.commands.registry import Command, CommandContext, CommandType


async def handle_exit(ctx: CommandContext) -> None:
    request_exit = getattr(ctx.ui, "request_exit", None)
    if request_exit is None:
        ctx.ui.add_system_message("当前界面不支持 /exit（仅交互式界面可用）")
        return
    await request_exit()


EXIT_COMMAND = Command(
    name="exit",
    aliases=["quit"],
    description="优雅退出（打断回复并清理资源后关闭）",
    usage="/exit",
    type=CommandType.LOCAL,
    handler=handle_exit,
)
