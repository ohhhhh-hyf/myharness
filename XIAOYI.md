# XiaoYi（本仓库 = harness 本体）

这是一个**终端 AI 编程助手的源码仓库**：在终端里以 TUI 交互（也支持 `-p` 单次提问），
调用大模型完成代码任务，具备工具调用、权限确认、MCP、子智能体、hooks、记忆与技能系统。

## 技术栈
- Python >= 3.11；uv 管环境与依赖（uv.lock 锁定版本），hatchling 构建
- 终端 UI：Textual（xiaoyi/app.py + styles.tcss，自定义 NoAltScreenDriver）
- 模型客户端：anthropic / openai SDK；三种协议：anthropic | openai | openai-compat
- 其他：pydantic、pyyaml、mcp（MCP 客户端）、httpx；测试用 pytest + pytest-asyncio

## 常用命令
- 装/同步依赖：`uv sync`
- 启动 TUI：`uv run xiaoyi`（读取 .xiaoyi/config.yaml）
- 单发模式：`uv run xiaoyi -p "问题"`
- 跑测试：`uv run pytest -q`

## 目录速览（xiaoyi/）
- agent.py 主循环与上下文管理；app.py TUI（XiaoYiApp / ChatInput）；driver.py 终端驱动
- client.py 三个协议客户端；tools/ 工具注册与实现；permissions/ 权限矩阵与规则引擎
- mcp/ MCP 客户端与工具包装；agents/ 子智能体（内置 + .xiaoyi/agents/*.md）
- memory/ 记忆与 recall；skills/、hooks/、teams/、worktree/、commands/ 斜杠命令

## 代码规范
- commit message 用英文
- 变量/函数名 snake_case，类名 PascalCase，工具类以 Tool 结尾
- 注释与 docstring 用中文，与现有文件风格保持一致
- 改 TUI 时注意：程序化 clear()/insert() 不保证触发 Textual 的 Changed 事件，
  需要同步 UI 状态时要显式调用，不能只依赖事件

## 注意事项
- .xiaoyi/ 是运行时状态目录（日志/会话/权限规则/含 API key 的配置），不要提交、不要当项目源码修改
- MCP 工具命名约定：`mcp__<server>__<tool>`（双下划线）
- Windows 上 MCP 子进程命令要写 `npx.cmd`，裸 `npx` 会报 WinError 2；文件系统 server 是
  项目自带的 Python 实现（xiaoyi/mcp/servers/filesystem.py），用
  `uv run --no-sync python -m xiaoyi.mcp.servers.filesystem .` 启动，不依赖 Node

