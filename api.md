# AgentFlow 统一同步接口服务文档 (API Specification)

> **文档定位**：本文档专门定义与说明 AgentFlow 的**同步 HTTP API 规范**（包括主同步调用端点、流式同步事件端点及产物下载端点），供前后端对接、自动化集成与测试参考。  
> **服务协议**：HTTP/1.1，数据传输采用 JSON / UTF-8 编码。  
> **默认端口**：`8000`（或依环境变量 `AGENTFLOW_BASE_URL` 配置）。

---

## 1. URL 端点定义

| 端点类型 | 路径 | 方法 | 说明 |
|---|---|:---:|---|
| **同步执行** | `/api/agent/v1` | `POST` | **主接口**。阻塞执行直到任务完成，返回完整响应体 `TaskResponse` |
| **流式同步** | `/api/agent/v1/stream` | `POST` | **实时同步流**。请求参数与主接口完全一致，以 `application/x-ndjson` 逐行推送节点进度与文本增量 |
| **产物下载** | `/api/agent/v1/file/{request_id}/{file_name}` | `GET` | **附件下载**。下载指定请求生成的产物文件（`file_name` 取自执行响应的 `data.file_name`） |
| **静态预览** | `/data/{user_id}/output/{request_id}/{file_name}` | `GET` | **产物直接预览**。静态挂载端点，供 Web 视图或 iframe 直接渲染 HTML/Markdown |
| **健康检查** | `/api/v1/health` | `GET` | 服务健康探针，返回当前服务状态与基础版本信息 |

---

## 2. 通用交互协议

### 2.1 请求头规范 (Headers)

| Header 名称 | 必填 | 适用端点 | 类型 | 说明 |
|---|:---:|---|:---:|---|
| `Content-Type` | **是** | POST 端点 | String | 固定为 `application/json` |
| `X-User-Id` | **是** | 全部端点 | String | 用户唯一标识。服务端所有用户资产（私有文档、向量知识库、会话记忆、产物目录）严格按照 `data/{user_id}/` 物理隔离 |
| `X-Request-Id` | 否 | POST 端点 | String | 客户端请求追踪 ID（推荐传 UUID）。缺省时服务端将基于分布式数字算法自动生成形如 `request_xxx` 的全局唯一 ID |

> [!NOTE]
> 产物存储目录以最终确定的 `request_id` 为名：`data/{user_id}/output/{request_id}/`。后续通过产物下载接口定位文件时必须使用相同的 `request_id`。

---

### 2.2 请求体格式 (`DomainTaskRequest`)

请求体由**定位字段**（`domain` 与 `task`）以及**执行参数**（`texts`、`docs`、`memory`、`extra`、`time`）组成：

```jsonc
{
  "domain": "meeting",              // [必填] 业务领域："meeting" (会议) 或 "notes" (笔记)
  "task": "minutes",                // [必填] 任务线标识（见第 3 节各任务清单）
  "memory": false,                  // [可选] 系统级长记忆开关，默认 false（会议跨场记忆/笔记增量图谱）
  "time": "2026-06-15 10:00",       // [可选] 任务时间（下沉至 extra.time，顶层保留以兼容历史客户端）
  "texts": {                        // [可选] 结构化文本字典（严格限制仅支持以下 3 个 key）
    "transcript": "...",            //   会议转写全文 / 课堂转写 / 笔记正文（多段以 \n 拼接）
    "keypoints": "",                //   用户重点记录（minutes_trace 溯源线必填）
    "notes": ""                     //   用户随堂速记（minutes_trace 溯源线必填）
  },
  "docs": [],                       // [可选] 材料文件名列表（须已上传至服务端 data/{user_id}/docs/ 目录下）
  "extra": {                        // [可选] 任务专属控制参数对象
    "template": "",                 //   输出模板标识（英文名如 general_minutes 或中文名如 通用纪要）
    "profile": "",                  //   用户画像选档：""/objective=客观全员；user=真人档案；或预设职业名
    "project": "",                  //   关联项目名（配合 memory=true 实现跨会议状态机追踪）
    "style": "",                    //   组织模式（仅 minutes_styles 必填，严格限 5 大黄金模式）
    "agenda_txt": "",               //   纯文本议程单（仅 agenda_minutes 使用，支持与 docs 图片/文档智能合并）
    "subject": "",                  //   学科名称（notes 域必填，中文自动转拼音存储，如 物理→wuli）
    "catalog": "",                  //   基准目录版本文件名（checklist 任务定位使用，如 20261001_100000.json）
    "time": ""                      //   会议召开时刻（如 2026-06-15 10:00，缺省为空）
  }
}
```

#### 请求参数字段明细表

| 字段路径 | 类型 | 必填 | 默认值 | 约束与细节说明 |
|---|:---:|:---:|:---:|---|
| `domain` | String | **是** | - | 仅支持 `"meeting"` 或 `"notes"`，大小写不敏感（非法值返回 400） |
| `task` | String | **是** | - | 任务线标识，必须在所选 domain 的已注册清单内（不匹配返回 404） |
| `memory` | Boolean | 否 | `false` | 长记忆开关。开启后自动检索历史关联事项并在正文中生成溯源引用标记，同时持久化本场记忆 |
| `texts` | Object | 否 | `{}` | **校验限制**：字典 key 仅允许出现 `transcript`、`keypoints`、`notes` 中的一个或多个；**出现任何未知 key 会直接被 Pydantic 校验抛出 422 错误** |
| `docs` | Array[String]| 否 | `[]` | 文件名数组。文件必须已放置在服务端 `data/{user_id}/docs/` 或公共 `data/docs/` 下，支持 `.txt/.md/.docx/.pdf/.pptx/.xlsx` 及图片 `.jpg/.png`（图片自动调用底层 OCR 引擎与 LLM 整理） |
| `extra.template` | String | 否 | `""` | 模板名称。可填写模板 ID（如 `project_progress`）或中文名（如 `项目进度会`）。`minutes` 线留空时自动套用默认模板 |
| `extra.profile` | String | 否 | `""` | 选档规则：<br>• 空串 / `"objective"` / `"object"`：**默认客观全员档**（无偏中立总结）；<br>• `"user"`：**真人模式**（读取 `data/{user_id}/user.json`，专属裁剪本人待办与关注域）；<br>• 职业模板（如 `"developer"`, `"project_manager"`, `"product_manager"`, `"tester"`）：读取内置职业画像 |
| `extra.style` | String | 否 | `""` | **仅供 `minutes_styles` 任务使用**。严格限定为 5 种模式：`brief` / `topic` / `review` / `retro` / `alignment` |
| `extra.agenda_txt` | String | 否 | `""` | **供 `agenda_minutes` 任务使用**。支持直接通过文本传输议程内容（兼容历史别名 `extra.agenda`） |
| `extra.subject` | String | 否 | `""` | **notes 域知识任务必填**。中文学科名称（系统内部自动转换为小写拼音，如 `历史`→`lishi`） |
| `extra.catalog` | String | 否 | `""` | **供 `checklist` 任务使用**。指定参考的知识目录 JSON 文件名；留空时自动读取该学科最新一份目录 |
| `extra.project` | String | 否 | `""` | 记忆归集项目名。留空时系统基于会议首要主题自动提炼核心名进行平滑接续 |

---

### 2.3 响应体规范 (`TaskResponse`)

#### 2.3.1 成功响应格式 (HTTP 200)

```jsonc
{
  "code": 0,                        // 业务状态码：0 代表成功
  "request_id": "req_8a7c29ef",     // 回显调用方传入的追踪 ID 或服务端生成的 ID
  "message": "success",
  "quality_warning": null,          // [条件出现] 质量预警信息；正常生成时不包含该 key
  "monitor": {                      // 运行监控度量指标
    "token_usage": 12850,           //   本次任务消耗的大模型总 Token
    "cache_hit": 6400,              //   上下文缓存命中 Token (KV Cache)
    "cost_time": 24.5               //   执行总耗时（秒）
  },
  "data": {                         // 任务输出产物
    "text": "# 会议纪要标题\n\n## 一、核心结论...", // Markdown 格式完整正文
    "file_name": "minutes.html"     // 主要产物文件名（可用于附件下载或静态预览）
  }
}
```

#### 2.3.2 字段说明

- **`quality_warning`（质量预警信号）**：  
  仅当本次生成触发降级策略（如未通过内审规则、审核模块网络异常重试超限、或指定的 `extra.project` 与会议事实无重叠）时出现。正文内容依然完整输出，但提示调用端结合原文重点核对。
- **`monitor.token_usage` / `cache_hit` / `cost_time`**：  
  全面记录本次推理的算力消耗与物理耗时。
- **`data.text`**：  
  纯文本产物。对大多数任务为标准 Markdown；对 `checklist` 任务为统计与清单摘要；对 `library` 入库任务为解析统计。
- **`data.file_name`**：  
  本次任务落盘的主产物文件名。如果生成了 Web 交互卡片则为 `{task}.html`；纯文本落盘为 `{task}.md` 或 `result.md`；若任务无落盘文件（如 `library` 知识入库）则返回空字符串 `""`。

---

### 2.4 异常响应与 HTTP 状态码规范

当请求发生异常或校验失败时，服务端以对应的 HTTP 状态码返回精简的错误体，**不输出 `monitor` 和 `data`**：

```jsonc
{
  "code": 400,                      // 业务状态码（与 HTTP 状态码保持严格一致）
  "request_id": "req_8a7c29ef",     // 追踪 ID
  "message": "minutes 缺少必填项：texts 中 transcript（会议转写文本）"
}
```

| HTTP 状态码 | 对应场景 | 常见原因与排查指南 |
|:---:|---|---|
| **`400 Bad Request`** | 业务前置校验失败 | • 缺失必填参数（如未传 `X-User-Id` 或任务必需文本）<br>• 非法枚举值（如 `extra.style` 不是 5 种模式之一）<br>• 非法模板名（`extra.template` 不在系统模板注册表中）<br>• 非法画像名（`extra.profile` 指定的文件不存在） |
| **`404 Not Found`** | 资源或任务线不存在 | • 域不存在或任务线不存在（如 `domain=meeting, task=quiz` 会干净报 404）<br>• `docs` 指定的文件在 `data/{user_id}/docs/` 下不存在<br>• 调用下载接口时产物文件不存在 |
| **`422 Unprocessable`** | JSON 请求体协议校验失败 | • 请求体非有效 JSON 格式<br>• `texts` 包含了未知 key（如误传入了 `"content"` 或 `"text"`）<br>• 缺少必填顶层字段 `domain` 或 `task` |
| **`500 Internal Error`** | 服务内部运行错误 | • 大模型底层调用异常、网络中断或超时<br>• 图编排运行期不可恢复错误 |

---

### 2.5 附件下载与文件定位规范

#### 2.5.1 产物下载端点 (`GET /api/agent/v1/file/{request_id}/{file_name}`)

客户端在普通同步接口得到响应后，可直接依据返回的 `request_id` 与 `data.file_name` 请求下载文件：

- **URL 路径参数**：
  - `request_id`：执行时绑定的请求 ID（对应响应中的 `request_id`）
  - `file_name`：产物文件名（如 `minutes.html`、`minutes.md`、`result.md`）
- **用户身份传递（二选一，均有效）**：
  - URL Query 参数：`?user_id=1001`
  - 请求头：`X-User-Id: 1001`
- **响应说明**：以 `application/octet-stream` 返回强制下载文件流。

```bash
# 方式 1：通过 Query 参数传入 user_id
curl -OJ "http://127.0.0.1:8000/api/agent/v1/file/req_8a7c29ef/minutes.html?user_id=1001"

# 方式 2：通过 Header 传入 X-User-Id
curl -OJ "http://127.0.0.1:8000/api/agent/v1/file/req_8a7c29ef/minutes.html" \
  -H "X-User-Id: 1001"
```

#### 2.5.2 静态预览端点 (`GET /data/{user_id}/output/{request_id}/{file_name}`)

对于浏览器端展示，服务将根目录 `data/` 挂载为静态文件服务：

```html
<!-- 直接嵌入 iframe 展示 HTML 产物面板 -->
<iframe src="http://127.0.0.1:8000/data/1001/output/req_8a7c29ef/minutes.html" width="100%" height="800px"></iframe>
```

---

## 3. 接口业务详情与任务清单

### 3.1 会议域任务清单 (`domain: "meeting"`, 共 8 个任务)

会议域所有任务共享底层会议理解核心，输出针对特定管理场景的高保真决策与行动事实。

#### 3.1.1 标准会议纪要 (`task: "minutes"`)
- **业务定位**：生成高质量综合会议纪要，支持客观全员视角与个人视角，内置 30+ 款专业场景样式模板。
- **必填项**：`texts.transcript`（会议转写原文）。
- **个性化选档**：
  - `extra.profile="user"`：自动加载 `data/{user_id}/user.json`，启用**个人专属纪要模式**，优先提炼本人承接事项与相关议题，自动套用 `personal_minutes` 模板；
  - `extra.profile=""`（默认）：客观全员模式，自动套用 `general_minutes` 模板。
- **长记忆接续**：`memory=true` 时自动关联历史会议并生成 `第 N 场` 连续编号与历史决策对照。
- **产物文件**：`minutes.html`（交互页面版）+ `result.md`（标准 Markdown）。

```bash
curl -X POST http://127.0.0.1:8000/api/agent/v1 \
  -H "Content-Type: application/json" \
  -H "X-User-Id: 1001" \
  -d '{
    "domain": "meeting",
    "task": "minutes",
    "texts": { "transcript": "张工：今天讨论缓存架构...李总：同意按方案二执行，下周五前上线。" },
    "extra": { "profile": "user" }
  }'
```

#### 3.1.2 待办事项提炼 (`task: "actions"`)
- **业务定位**：精准提取会议中的落定行动、分工任务、指派意向与整改要求，明确负责人、完成时限、前置条件与原文依据。
- **必填项**：`texts.transcript`。
- **输出特色**：生成工单看板与分类任务表，支持按人认领。
- **产物文件**：`actions.html` + `actions.md`。

#### 3.1.3 风险隐患分析 (`task: "risks"`)
- **业务定位**：专门挖掘会议中提出的进度阻碍、资源卡点、技术缺陷、外部依赖等风险信号。
- **必填项**：`texts.transcript`。
- **输出特色**：输出风险等级、影响面、已有缓解措施、责任人与原文证据链。
- **产物文件**：`risks.html` + `risks.md`。

#### 3.1.4 多样式纪要 (`task: "minutes_styles"`)
- **业务定位**：按特定高频业务诉求对会议事实进行重构排版。
- **必填项**：`texts.transcript`，且 **`extra.style` 必填**。
- **严格限定的 5 大组织模式 (`extra.style`)**：
  1. `brief`（高管速览）：金字塔汇报结构，核心态势先行，压缩铺叙篇幅；
  2. `topic`（业务归类）：按业务大类清晰聚类（架构/运营/交付），跨议题归纳；
  3. `review`（方案权衡）：突出方案选型演进、主备方案得失、技术代价与最终拍板决策；
  4. `retro`（复盘攻坚）：聚焦历史偏差根因、阻碍卡点排查与根本预防对策；
  5. `alignment`（多方对齐）：突出跨团队职责接口、共识结论与协同分工边界。
- **产物文件**：`minutes_styles.html` + `minutes_styles.md`。

```bash
curl -X POST http://127.0.0.1:8000/api/agent/v1 \
  -H "Content-Type: application/json" \
  -H "X-User-Id: 1001" \
  -d '{
    "domain": "meeting",
    "task": "minutes_styles",
    "texts": { "transcript": "..." },
    "extra": { "style": "brief" }
  }'
```

#### 3.1.5 溯源会议纪要 (`task: "minutes_trace"`)
- **业务定位**：将用户在会议期间记录的重点笔记与录音转写原文进行严密双向对齐，结论带原文溯源钉。
- **必填项**：
  - `texts.transcript`（会议录音转写原文）；
  - `texts.keypoints`（用户关键点标注）；
  - `texts.notes`（用户随堂笔记）。
- **产物文件**：`minutes_trace.html`（双栏审阅页，左侧正文，右侧点击高亮溯源证据）+ `minutes_trace.md`。

#### 3.1.6 交互思维导图 (`task: "mindmap"`)
- **业务定位**：将会议议题树与核心决议快速转化为交互式思维导图与缩进大纲。
- **必填项**：`texts.transcript`。
- **产物文件**：`mindmap.html`（基于 Markmap.js 渲染的动态可折叠 SVG/HTML 单文件）+ `mindmap.md`（树状缩进大纲）。

#### 3.1.7 议程对齐纪要 (`task: "agenda_minutes"`)
- **业务定位**：依据会议既定的会前议程单（包含议题、主讲人、预定时长等），对录音转写进行逐项对照审校，输出各议题达成状态、讨论结论与跳过议程标记。
- **必填项**：
  - `texts.transcript`（会议录音全文）；
  - **议程内容（二选一或同时传入）**：
    1. 通过 `extra.agenda_txt` 直接传纯文本议程（推荐）；
    2. 通过 `docs` 传入议程文件或截图（如 `["agenda.png"]`，服务端自动并发 OCR 并清洗）。
- **产物文件**：`agenda_minutes.html` + `agenda_minutes.md`。

#### 3.1.8 共识决策备忘录 (`task: "consensus_decision"`)
- **业务定位**：专注于提炼会议中“方案如何通过沟通最终定调”，清晰呈现主案主张、协同各方提出的优化打磨建议、执行边界以及最终形成的共识结论。
- **必填项**：`texts.transcript`。
- **模板机制**：默认自动套用 `resources/templates/consensus_decision.md` 模板。
- **产物文件**：`consensus_decision.html` + `consensus_decision.md`。

---

### 3.2 笔记域任务清单 (`domain: "notes"`, 共 6 个任务)

笔记域专注于多模态教研材料入库、知识目录自适应构建与智能化复习助学。

#### 3.2.1 笔记知识图谱 (`task: "graph"`)
- **业务定位**：解析课堂笔记、板书与教材，提取核心知识概念节点与前后承接前置依赖关系，生成可视化知识网。
- **输入要求**：
  - `texts.transcript` 或 `texts.notes`，或者通过 `docs` 传入材料文件（图片自动 OCR 并经 LLM 版面重构）；
  - `extra.subject`（必填）：学科名称，用于按学科沉淀图谱数据；
  - `memory=true` 时支持跨会话增量合并，新学习知识点在图中高亮显示。
- **产物文件**：`graph.html`（基于 Cytoscape.js 渲染的高清交互力导向图，支持缩放/拖拽/点击探针）。

#### 3.2.2 资料批量入库 (`task: "library"`)
- **业务定位**：将用户上传的教学 PPT、Word 文档、PDF 讲义、Excel 课表或板书图片解析、分块并构建向量索引。
- **必填项**：`extra.subject` + `docs`（文件名必须非空且真实存在）。
- **特性说明**：**本任务为纯入库构建索引操作，不生成落盘下载文件**。`data.file_name` 为空串，`data.text` 返回解析成功的文档与块数统计。

#### 3.2.3 知识目录自动构建 (`task: "catalog"`)
- **业务定位**：基于用户已入库资料（或配合老师重点 txt）自适应提炼标准树状教学大纲（章 → 节 → 知识点）。
- **输入要求**：
  - `extra.subject`（必填，学科名）；
  - `docs`（可选）：若包含 `.txt` 文件将自动识别为老师划定的核心考点大纲。
- **保序原则**：严格跟随教材材料原始先后顺序编排，不随意打乱。
- **产物输出**：
  - 目录数据写入 `data/{user_id}/knowledge/catalogs/{学科拼音}/{时间戳}.json`；
  - `data.file_name` 返回生成的 catalog JSON 文件名（供下一步复习清单使用）；
  - `data.text` 返回格式化的目录 Markdown 树。

#### 3.2.4 结构化复习清单 (`task: "checklist"`)
- **业务定位**：以已生成的知识目录为基准框架，提取各考点核心要义、公式卡片与记忆要诀。
- **必填项**：
  - `extra.subject`（必填，学科名）；
  - `extra.catalog`：知识目录文件名（即 `catalog` 任务返回的 `data.file_name`，如 `"20261001_100000.json"`；为兼容老版本，也可在 `docs` 中传入该 `.json` 文件名）。
- **产物文件**：`checklist.html`（富交互复习抽认卡片）+ `result.md`；`data.text` 返回卡片列表精简统计。

#### 3.2.5 考点复习提纲 (`task: "review"`)
- **业务定位**：按学科和知识库检索相关考点，输出结构化的重点知识背诵与复习提纲。
- **必填项**：`extra.subject`，且输入 `texts` 或 `docs` 至少包含一项。
- **产物文件**：`review.html` + `review.md`。

#### 3.2.6 考点自测题库 (`task: "quiz"`)
- **业务定位**：基于学科知识点自动命制自测试题（含单选、多选、概念简答与详细解析）。
- **必填项**：`extra.subject`，且输入 `texts` 或 `docs` 至少包含一项。
- **产物文件**：`quiz.html` + `quiz.md`。

---

## 4. 核心任务输入输出矩阵速查表

| Domain | Task | 中文名称 | 核心必填字段 | 常用 extra 参数 | 主产物文件 (`file_name`) |
|:---:|:---:|---|---|---|---|
| `meeting` | `minutes` | 标准会议纪要 | `texts.transcript` | `profile`, `template`, `memory` | `minutes.html` |
| `meeting` | `actions` | 待办事项提取 | `texts.transcript` | - | `actions.html` |
| `meeting` | `risks` | 风险隐患分析 | `texts.transcript` | - | `risks.html` |
| `meeting` | `minutes_styles` | 多样式纪要 | `texts.transcript`, `extra.style` | `style` (5选1) | `minutes_styles.html` |
| `meeting` | `minutes_trace` | 溯源会议纪要 | `texts` 全套 (transcript + keypoints + notes) | - | `minutes_trace.html` |
| `meeting` | `mindmap` | 交互思维导图 | `texts.transcript` | - | `mindmap.html` |
| `meeting` | `agenda_minutes` | 议程对齐纪要 | `texts.transcript`, 议程来源 | `agenda_txt` 或 `docs` 附件 | `agenda_minutes.html` |
| `meeting` | `consensus_decision` | 共识决策备忘录 | `texts.transcript` | `template` | `consensus_decision.html` |
| `notes` | `graph` | 笔记知识图谱 | `extra.subject`, 材料输入 | `subject`, `memory` | `graph.html` |
| `notes` | `library` | 资料解析入库 | `extra.subject`, `docs` | `subject` | `""` (无文件下载) |
| `notes` | `catalog` | 知识目录构建 | `extra.subject` | `subject`, `docs` 老师重点 | `{时间戳}.json` |
| `notes` | `checklist` | 结构化复习清单 | `extra.subject`, `extra.catalog` | `subject`, `catalog` | `checklist.html` |
| `notes` | `review` | 考点复习提纲 | `extra.subject`, 材料输入 | `subject` | `review.html` |
| `notes` | `quiz` | 考点自测题库 | `extra.subject`, 材料输入 | `subject` | `quiz.html` |

---

## 5. 常见调用代码示例

### 5.1 Python 调用完整示例 (Requests)

```python
import uuid
import requests

BASE_URL = "http://127.0.0.1:8000"
USER_ID = "user_dev_01"
REQUEST_ID = f"req_{uuid.uuid4().hex[:12]}"

# 1. 发起同步任务调用（例如：高管速览多样式纪要）
payload = {
    "domain": "meeting",
    "task": "minutes_styles",
    "texts": {
        "transcript": "李总：今天开会通报Q3季度研发进度。王工：核心通信引擎已完成灰度发布，时延下降35%。赵工：海外节点上云受当地合规审计影响滞后一周。李总：合规问题由法务部下周二前拉齐专项解决，其余按既定目标交付。"
    },
    "extra": {
        "style": "brief"
    }
}

headers = {
    "Content-Type": "application/json",
    "X-User-Id": USER_ID,
    "X-Request-Id": REQUEST_ID,
}

response = requests.post(
    f"{BASE_URL}/api/agent/v1",
    json=payload,
    headers=headers,
    timeout=180
)

result = response.json()
print("HTTP Status :", response.status_code)
print("Code        :", result.get("code"))
print("Message     :", result.get("message"))

if result.get("code") == 0:
    monitor = result.get("monitor", {})
    data = result.get("data", {})
    print(f"Cost Time   : {monitor.get('cost_time')} s")
    print(f"Total Tokens: {monitor.get('token_usage')}")
    print(f"Output File : {data.get('file_name')}")
    print("\n--- Markdown 产物片段 ---")
    print(data.get("text", "")[:300] + "...\n")
    
    # 2. 如果产物文件存在，下载 HTML 页面版
    file_name = data.get("file_name")
    if file_name:
        download_url = f"{BASE_URL}/api/agent/v1/file/{REQUEST_ID}/{file_name}?user_id={USER_ID}"
        file_resp = requests.get(download_url)
        if file_resp.status_code == 200:
            with open(file_name, "wb") as f:
                f.write(file_resp.content)
            print(f"产物已保存到本地: {file_name}")
else:
    print("调用失败:", result.get("message"))
```

### 5.2 笔记闭环三步流示例 (Curl)

```bash
# 第一步：教研材料入库（需预先将讲义放入 data/1001/docs/lecture1.pdf）
curl -s -X POST http://127.0.0.1:8000/api/agent/v1 \
  -H "Content-Type: application/json" -H "X-User-Id: 1001" \
  -d '{"domain":"notes","task":"library","docs":["lecture1.pdf"],"extra":{"subject":"物理"}}'

# 第二步：基于已入库资料生成知识目录大纲（响应中获取 data.file_name，如 20261009_170000.json）
curl -s -X POST http://127.0.0.1:8000/api/agent/v1 \
  -H "Content-Type: application/json" -H "X-User-Id: 1001" \
  -d '{"domain":"notes","task":"catalog","extra":{"subject":"物理"}}'

# 第三步：基于生成的目录版本生成复习抽认清单
curl -s -X POST http://127.0.0.1:8000/api/agent/v1 \
  -H "Content-Type: application/json" -H "X-User-Id: 1001" \
  -d '{"domain":"notes","task":"checklist","extra":{"subject":"物理","catalog":"20261009_170000.json"}}'
```
