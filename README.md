# XiaoYi

XiaoYi 是一个运行于终端的 AI 编程助手（AI Coding Agent）。它在真实项目目录中工作，
通过大模型驱动工具调用来完成代码阅读、检索、修改、执行与验证等任务，并内置权限确认、
上下文管理、长期记忆、MCP 扩展与子智能体协作等完整能力。

XiaoYi 以 TUI（终端用户界面）为主要交互形态，同时提供非交互的一次性执行模式，便于
集成到脚本与自动化流程中。

## 主要特性

- **终端原生界面**：基于 Textual 构建，支持流式输出、工具调用可视化、命令补全与用法提示；
  退出后对话内容保留在终端回看（scrollback）中。
- **多模型接入**：支持 Anthropic、OpenAI 以及任意 OpenAI 兼容端点（如 DeepSeek、
  GLM、Qwen、本地推理服务等），三种协议可自由切换。
- **完整的工具体系**：文件读写、目录遍历、内容检索、命令执行等内置工具，配合权限矩阵、
  危险命令检测与路径沙箱形成多层防护。
- **MCP 支持**：可作为 MCP 客户端接入 stdio 与 Streamable HTTP 两类服务器，其工具自动
  注册进工具表供模型调用。
- **子智能体**：内置 Explore（只读检索）、Plan（方案规划）、Verification（结果验证）与
  general-purpose（通用任务）四类子智能体，并支持通过 Markdown 定义项目/用户级自定义
  子智能体；子任务在后台执行并在完成后自动回报。
- **记忆系统**：自动从对话中提炼要点形成长期记忆，并在后续请求中按相关性检索注入；
  记忆以可读的 Markdown 文件存放在项目与用户两级目录中。
- **上下文管理**：工具结果落盘与剪枝、超限自动压缩（摘要替换历史）、会话持久化与文件级
  回溯（rewind）。
- **可扩展机制**：技能（Skills）、钩子（Hooks）与斜杠命令体系，支持项目级与用户级扩展。

## 环境要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/)（依赖与虚拟环境管理）
- 操作系统：Windows / macOS / Linux
- 可选：使用基于 Node.js 的 MCP 服务器时需安装 Node.js；使用基于 Python 的 MCP 服务器
  时需安装 uv

## 安装与快速开始

### 1. 安装 uv

```bash
pip install uv
```

### 2. 创建配置文件

在项目根目录下创建 `.xiaoyi/` 目录，并在其中放置 `config.yaml`（也可以放到用户级目录
`~/.xiaoyi/config.yaml`，对所有项目生效），最小配置示例如下：

```yaml
providers:
  - name: deepseek
    protocol: openai-compat
    base_url: https://api.deepseek.com
    model: deepseek-v4-flash
    api_key: ""            # 留空则从环境变量读取（openai 系列读 OPENAI_API_KEY）
```

### 3. 同步依赖并启动

```bash
uv sync           # 安装依赖并创建虚拟环境
uv run xiaoyi     # 启动交互式界面
```

非交互模式（执行单条指令并输出结果）：

```bash
uv run xiaoyi -p "解释这个项目的目录结构"
```

也可以在已有的 Python 环境（如 Miniconda 创建的虚拟环境）中安装使用：

```bash
uv pip install -e . --python <环境解释器路径>   # 或在该环境内执行 pip install -e .
xiaoyi                                        # 直接使用环境中的命令
```

启动时可通过 `--mode` 覆盖配置文件中的权限模式：

```bash
uv run xiaoyi --mode acceptEdits
```

## 配置说明

配置文件按以下顺序加载并逐层合并（后者覆盖前者，MCP 服务器按名称合并，钩子叠加）：

1. `~/.xiaoyi/config.yaml`（用户级）
2. `<项目>/.xiaoyi/config.yaml`（项目级）
3. `<项目>/.xiaoyi/config.local.yaml`（本地覆盖，通常不入版本库）

### providers

模型提供方列表，至少配置一项。字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 提供方标识 |
| `protocol` | 是 | `anthropic`、`openai` 或 `openai-compat` |
| `base_url` | 是 | API 地址 |
| `model` | 是 | 模型名称 |
| `api_key` | 否 | 留空则回退到环境变量（`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`） |
| `thinking` | 否 | 是否启用推理模式，默认 `false` |
| `vision` | 否 | 是否支持图片输入，默认开启；接入不支持图片的模型时设为 `false` |
| `context_window` | 否 | 上下文窗口（token），默认自动解析 |
| `max_output_tokens` | 否 | 单次最大输出 token，默认使用内置值 |

### permission_mode

权限模式决定各类操作的处理方式：读类操作放行，写文件与执行命令按模式处理。

| 模式 | 读取 | 写文件 | 执行命令 |
| --- | --- | --- | --- |
| `default` | 放行 | 询问 | 询问 |
| `acceptEdits` | 放行 | 放行 | 询问 |
| `plan` | 放行 | 询问 | 询问 |
| `bypassPermissions` | 放行 | 放行 | 放行 |
| `dontAsk` | 放行 | 放行 | 放行 |
| `custom` | 询问 | 询问 | 询问 |

此外还支持三层权限规则文件（用户级 / 项目级 / 本地级 `permissions.yaml`），用于对特定
工具与命令模式做精细控制。

### mcp_servers

MCP 服务器列表，`command`（stdio）与 `url`（Streamable HTTP）二选一：

```yaml
mcp_servers:
  # 项目自带的文件系统 server（12 个工具，名称与官方 Node 版一致）：uv 拉起，不依赖 Node/npx
  - name: filesystem
    command: uv
    args: ["run", "--no-sync", "python", "-m", "xiaoyi.mcp.servers.filesystem", "."]
  # 外部 server 走 npm 时，Windows 下需带 .cmd 后缀
  - name: git
    command: npx.cmd
    args: ["-y", "@modelcontextprotocol/server-git", "D:/project"]
  - name: remote
    url: https://example.com/mcp
    headers:
      Authorization: Bearer ${MCP_TOKEN}   # 支持 ${环境变量} 展开
```

`xiaoyi/mcp/servers/` 放项目自带的 server 实现。`--no-sync` 让子进程启动时不触发环境重装
（harness 自身占着 `.venv` 里的 `xiaoyi.exe` 时重装会失败）；该命令要求 `uv` 在 PATH 上、
且工作目录是项目根——子进程继承 harness 的工作目录，末尾的 `.` 即"允许访问启动目录"。

### hooks

生命周期钩子，支持 `session_start`、`turn_start`、`pre_tool_use`、`post_tool_use`、
`file_change`、`error`、`shutdown` 等事件，动作类型包括 `command`、`prompt`、`http`、
`agent`。`pre_tool_use` 可配合 `reject` 拦截工具调用，其余事件可声明 `async` 异步执行。

### 其他开关

| 配置项 | 默认 | 说明 |
| --- | --- | --- |
| `enable_fork` | `false` | 允许子智能体继承当前对话上下文 |
| `enable_verification_agent` | `false` | 启用内置 Verification 验证子智能体 |
| `enable_rag` | `false` | 启用本地 RAG 知识库（检索证据自动注入 + KnowledgeSearch 工具） |
| `teammate_mode` | `""` | 团队协作模式，可选 `in-process` |
| `enable_coordinator_mode` | `false` | 启用协调者模式 |
| `worktree` | 见下 | Git worktree 相关配置 |

```yaml
worktree:
  symlink_directories: ["node_modules", ".venv", "vendor"]
  stale_cleanup_interval: 3600
  stale_cutoff_hours: 24
```

## 使用指南

### 快捷键

| 按键 | 作用 |
| --- | --- |
| `Esc` | 打断正在生成的回复（弹窗打开时优先关闭弹窗） |
| `Shift+Tab` | 循环切换权限模式 |
| `Tab` | 命令补全；输入 `/` 时弹出命令列表 |
| `Ctrl+C` | 回复生成中为打断；空闲时为退出 |
| `Ctrl+O` | 折叠 / 展开工具调用块 |
| `PageUp` / `PageDown` | 滚动对话区域 |
| `↑` / `↓` | 浏览输入历史 |

输入以 `/` 开头即为命令；输入 `@` 可引用项目内文件路径。

### 图片输入

终端不传输图片数据，但支持"拖拽即附件"：把图片文件**拖入终端**，或在文件管理器中
**复制该图片后粘贴**（终端插入的是文件路径），提交时会自动识别为图片附件：

- 支持格式：`png` / `jpg` / `jpeg` / `gif` / `webp`，单张上限 5MB，超出会降级为文字说明；
- **路径与文字之间无需留空格**：拖拽或粘贴得到的路径可以紧贴前后文字
  （`D:\a\shot.png这个报错怎么看`、`看一下D:\a\shot.png` 都能正确切分），
  多个粘连的路径也会被逐一识别；
- 路径会从消息正文中移除，聊天区以 `[图片] 文件名` 标记显示，并按协议转换为对应模型
  的图片块（Anthropic `image`、Responses API `input_image`、Chat Completions `image_url`）；
- 图片默认随请求直接发送（模型需支持多模态）；仅在接入不支持图片输入的模型时，才需要
  在 provider 上设置 `vision: false` 关闭发送；
- 图片文件的**只读访问不受路径沙箱限制**：任意目录（桌面、下载、截图目录等）中的图片都
  可以作为附件或直接被读取；写操作仍受沙箱约束。

### 斜杠命令

| 命令 | 说明 |
| --- | --- |
| `/help [命令名]` | 查看帮助与命令用法 |
| `/status` | 查看会话状态（模型、token 用量等） |
| `/clear` | 清除当前对话历史 |
| `/compact [保留重点]` | 压缩对话历史（摘要替换） |
| `/plan [任务描述]` | 进入规划模式，产出实现方案 |
| `/review [额外关注点]` | 审查当前改动 |
| `/permission [模式 \| rules \| add \| reset]` | 查看或切换权限模式、管理规则 |
| `/mcp` | 查看 MCP 服务器连接状态与工具清单 |
| `/memory [list \| clear \| edit]` | 管理长期记忆 |
| `/skill list \| info \| reload` | 管理技能 |
| `/session [list \| resume \| new \| delete]` | 管理会话 |
| `/rewind [序号]` | 回退到历史检查点 |
| `/tasks [info \| cancel] [id]` | 查看或取消后台任务 |
| `/trace` | 查看子智能体调用链 |
| `/worktree <create \| list \| enter \| exit \| status>` | 管理 Git worktree |
| `/exit`（别名 `/quit`） | 优雅退出（先清理资源再关闭） |

### 退出

推荐使用 `/exit` 退出：正在生成的回复会被打断，随后依次执行记忆提炼、`shutdown` 钩子、
MCP 连接关闭、会话落盘等清理动作。空闲状态下按 `Ctrl+C` 具有相同效果。

## RAG 知识库（可选）

`xiaoyi/rag/` 内置一套离线 RAG 检索模块（知识源为 `xiaoyi/rag/data/*.md`）：

```bash
python xiaoyi/rag/build_index.py            # 入库：切块 + bge-m3 嵌入 → xiaoyi/rag/index/rag_index.json.gz
python xiaoyi/rag/query.py "小艺慧记有什么限制"   # 只测检索（含 RRF 与 bge 精排）
```

在 `.xiaoyi/config.yaml` 打开开关即接入对话：

```yaml
enable_rag: true     # 需要 xiaoyi/rag/.env 配置 EMBED_API_KEY / RERANK_API_KEY
```

开启后每轮对话会并行做两件事（失败静默，不阻塞）：

1. **自动预取注入**：检索命中后把证据段落以 `system-reminder` 注入本轮上下文，
   并在界面提示 "知识库命中 N 条证据"；
2. **KnowledgeSearch 工具**：模型判断需要深入查证时可自行调用（不受门控限制，
   是漏检时的兜底），返回带小节名与来源文件的证据段落。

检索前经过**三层门控**，避免无关对话也付代价（实测：无关问题 0~18ms 直接跳过，
域内问题约 1.6s 完成注入）：

| 层 | 判据 | 成本 |
| --- | --- | --- |
| ① 关键词/实体（含最近几轮话题承接） | 命中域内词表（小艺/鸿蒙/慧记/唤醒词…） | 零（本地 <1ms） |
| ② 相似度 | 查询与知识库的最大余弦 ≥ `RAG_GATE_MIN_SIMILARITY`（默认 0.55） | 一次嵌入（~0.12s）+ 本地点积 |
| ③ 重排分数 | 最高分 ≥ `RERANK_MIN_SCORE`（默认 0.3） | 已有 |

门控与检索**复用同一次嵌入**；词表与阈值都可在 `xiaoyi/rag/.env` 覆盖。

## 状态目录与项目指令

运行时状态统一存放在 `.xiaoyi/` 目录，与项目代码隔离：

| 路径 | 内容 |
| --- | --- |
| `.xiaoyi/config.yaml` | 项目配置 |
| `.xiaoyi/history` | 输入历史 |
| `.xiaoyi/sessions/` | 会话记录 |
| `.xiaoyi/debug.log` | 运行日志 |
| `.xiaoyi/permissions.yaml` | 权限规则 |
| `.xiaoyi/agents/`、`.xiaoyi/skills/` | 项目级子智能体与技能 |
| `.xiaoyi/memory/`、`.xiaoyi/memories.md` | 长期记忆 |
| `.xiaoyi/plans/`、`.xiaoyi/worktrees/` | 计划文件与工作树 |

项目指令文件按顺序读取并合并：`<项目>/XIAOYI.md`、`<项目>/.xiaoyi/XIAOYI.md`、
`~/.xiaoyi/XIAOYI.md`。指令文件支持 `@include 相对路径` 语法引入其他文档（限项目内，
最多嵌套 5 层）。

## 架构概览

```
xiaoyi/
├── app.py            # TUI 主程序（界面、事件分发、会话编排）
├── agent.py          # Agent 主循环与上下文管理
├── client.py         # 三种协议的大模型客户端
├── driver.py         # 终端驱动（保留 scrollback 的渲染方案）
├── config.py         # 配置加载与合并
├── conversation.py   # 对话模型
├── tools/            # 工具注册与实现
├── permissions/      # 权限矩阵、规则引擎、危险命令检测、路径沙箱
├── mcp/              # MCP 客户端与工具包装
├── agents/           # 子智能体加载与任务调度
├── memory/           # 长期记忆、指令文件、记忆检索
├── context/          # 上下文预算与压缩
├── skills/           # 技能系统与内置技能
├── hooks/            # 生命周期钩子
├── teams/            # 团队协作（tmux / iTerm2 / 进程内）
├── worktree/         # Git worktree 管理
├── commands/         # 斜杠命令注册与处理
└── filehistory/      # 文件修改历史（回溯支持）
```

## 开发与测试

```bash
uv sync --dev        # 安装开发依赖
uv run pytest -q     # 运行测试
```

## 注意事项

- Windows 环境下，MCP 的 stdio 服务器若通过 npx 启动，命令需写为 `npx.cmd`；直接写
  `npx` 会因可执行文件解析失败而报错。内网/公司网络里 npx 的依赖解析尤其不可靠（npx 缓存
  装到一半被打断后会一直报 `ERR_MODULE_NOT_FOUND`，且 npx 不会自行修复），所以文件系统
  server 改成了项目自带的 Python 实现（`uv run --no-sync python -m xiaoyi.mcp.servers.filesystem .`），
  完全绕开 Node。
- MCP 工具在工具表中的命名为 `mcp__<server>__<tool>`（双下划线）。
- 为保留对话的终端回看能力，界面不使用备用屏（alternate screen）渲染；退出时会自动清理
  界面占用区域。
