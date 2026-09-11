# xiaoyi/rag —— 离线 RAG 知识库

在 `rag/` 文件夹内**独立实现**的 RAG 检索模块：知识源是 `rag/data/` 下的 30 份小艺
Markdown 文档，逻辑参考（并从零重写、不依赖）参考项目 `xiaoyi_demo/` —— 后者删除后
本模块照常工作。

- **无相对导入、无包依赖**：各模块用绝对名互相导入，文件头部自带目录引导，
  可以直接用脚本方式运行；
- **不引入新依赖**：只用项目已有的 `openai`（嵌入）与 `httpx`（重排）；
  切块逻辑由参考项目的 langchain 版移植为纯 Python，行为对齐。

## 目录

| 文件 | 职责 |
| - | - |
| `config.py` | 读取 `rag/.env`（环境变量优先），三组上游与检索/切块参数 |
| `sources.py` | 扫描 `rag/data/*.md`：解析 `NN-类别-标题.md` → 类别/content_type；剥离 frontmatter |
| `chunking.py` | Markdown 层级切块：h1~h4 分节、表格保头切分、句级重叠、中文友好递归切分 |
| `documents.py` | 小节 → 结构化块：`category`（文档标题）/`questions`（小节标题）/`answer`（正文）/`section_path` |
| `embeddings.py` | bge-m3 嵌入（OpenAI 兼容端点） |
| `rerank.py` | bge-reranker-v2-m3 精排（`/rerank`，退避重试） |
| `localstore.py` | 本地索引：构建 / 缓存加载 / 向量余弦 / BM25(CJK 二元组) / RRF 融合 |
| `retrieval.py` | 检索编排：子句拆分、轮转合并、首尾组装工具（固定全链路：向量 + BM25 → RRF → 精排） |
| `build_index.py` | 入库 CLI（切块 + 嵌入 + 写索引） |
| `query.py` | 检索自测 CLI（不经过聊天模型，直接看召回/精排结果） |
| `data/` | 知识源（30 份 md，命名 `NN-类别-标题.md`） |

## 快速开始

在**项目根目录**执行（无需激活环境时用 `myharness` 环境的绝对解释器）：

```bash
# 1) 配置：复制模板并填密钥（.env 不入版本库）
cp xiaoyi/rag/.env.example xiaoyi/rag/.env

# 2) 入库：data/*.md → 切块 + 嵌入 → xiaoyi/rag/index/rag_index.json.gz
python xiaoyi/rag/build_index.py            # 缓存命中则秒回；文档有改动/首次才联网
python xiaoyi/rag/build_index.py --force    # 无视缓存，全量重嵌

# 3) 检索自测
python xiaoyi/rag/query.py "小艺慧记支持哪些功能，有什么限制" --k 4
python xiaoyi/rag/query.py "小艺的隐私保护" --k 3
python xiaoyi/rag/query.py "小艺帮记怎么用" --json
```

> 也可以 `cd xiaoyi/rag && python build_index.py`，或 `python -m xiaoyi.rag.build_index`
> 在项目根运行（两种方式都支持）。

## 配置（`rag/.env`）

| 分组 | 键 | 说明 |
| - | - | - |
| 嵌入 | `EMBED_BASE_URL` / `EMBED_MODEL` / `EMBED_API_KEY` | 默认硅基流动 `BAAI/bge-m3` |
| 重排 | `RERANK_BASE_URL` / `RERANK_MODEL` / `RERANK_API_KEY` | 默认 `BAAI/bge-reranker-v2-m3` |
| 兜底 | `SILICONFLOW_API_KEY` | 上面两个 KEY 留空时回退使用 |
| 检索 | `RECALL_TOP_K` / `CANDIDATE_TOP_K` / `KNOWLEDGE_TOP_K` | 三档：各路召回 → RRF 候选池 → 精排条数 |
| 门控 | `RAG_GATE_MIN_SIMILARITY` / `RAG_GATE_KEYWORDS` / `RERANK_MIN_SCORE` | 相似度门控阈值（0.55）/ 域内关键词覆盖 / 证据分阈值（0.3） |
| 优化 | `RAG_QUERY_CACHE_SIZE` / `RAG_DEDUPE_MIN_OVERLAP` / `RAG_CATEGORY_BOOST` | 查询嵌入缓存条数（64）/ 去重阈值（0.10）/ 目录软加权（0.1，0=关闭） |
| 归一化 | `RAG_ALIAS_NORMALIZE` / `RAG_ALIAS_MAP` | 同音错字纠正开关（默认开）/ 自定义映射（错字=正确） |
| 索引 | `RAG_INDEX_PATH` / `RAG_INDEX_STRICT` | 索引路径 / 严格校验（默认宽松，见"部署"一节） |
| 切块 | `KNOWLEDGE_CHUNK_SIZE` / `KNOWLEDGE_CHUNK_OVERLAP` | 默认 500 / 100（改动会触发重新入库） |

## 检索流水线（含两项优化）

```
query ──┬─ 子句拆分（一问多意图，如「…，另外…」）
        │
        ├─ 每子句：dense 余弦 Top-N  ＋  本地 BM25 Top-N  → RRF 融合(k=60) → 候选池
        │
        └─ bge-reranker 精排 → Top-K（含 rerank_score）
              ↓
        轮转合并（同小节去重）→ arrange_head_tail 防 lost-in-the-middle（生成侧使用）
```

### 优化一：查询嵌入缓存（LRU）

查询在嵌入前先做**归一化**（去空白/标点、统一小写）；归一化后相同的查询直接复用向量：
重复提问、只剩标点差异的追问都是 **0ms、零 API**。缓存条数 `RAG_QUERY_CACHE_SIZE`（默认 64）。

```
首次      "小艺慧记有什么限制"     1 次 API   ~1100ms
重复      "小艺慧记有什么限制"     0 次 API      0ms
追问      "小艺慧记有什么限制？"   0 次 API      0ms   ← 归一化后命中
```

### 优化二：注入去重（同源 / 近重）

同一事实常出现在多篇文档（"能力全景"与专题详解写同一组设置），或同文档内被表格切分重复。
判定用**长片段重合率**：归一化后取 12 字滑窗，`共享片段 / 较短文本片段` ≥ `RAG_DEDUPE_MIN_OVERLAP`
（默认 0.10）→ 视为同一事实，**只保留分数最高的一条**。

标定数据（7 个查询 × 10 对样本）：真重复 **0.17**（"使用前提"列表 vs "必做设置"表格，讲同三条设置），
其余组合 **≤0.03** —— 阈值 0.10 有约 3 倍余量。命中去重时结果里会带说明"已合并 N 条重复证据"。

## 索引与失效规则

- 产物：`xiaoyi/rag/index/rag_index.json.gz`（运行时状态目录，已在 .gitignore）；
  内容 = chunk 元数据 + float32 打包 base64 的归一化向量（30 份文档 ≈ 285 块 ≈ 1.0MB）；
- **缓存命中条件**（任一不符即要求重建）：索引版本、`EMBED_MODEL`、切块参数、
  以及全部源文件的 `size + mtime_ns` 指纹；
- **入库与检索解耦**：`query.py`/后续服务启动只读本地索引、不联网；
  仅 `build_index.py` 会调用嵌入接口。

### 优化三：目录路由 + 软加权（用 md 的分类信息）

知识库天然分了类（文件名 `NN-类别-标题.md` 的类别，以及每份文档的标题/小节标题）：

- **自动关键词表**：门控词表**从文档标题自动生成**（H1/H2 + 文件名标题切成短词，按文档频率
  剔除"常见问题/使用/设置"这类通用词，去掉纯数字与 `1+8+N` 之类的噪声），当前 **390 个词**；
  新增文档后自动覆盖，零维护。显式设置 `RAG_GATE_KEYWORDS` 时以显式值为准。
- **目录路由**：检索后按命中块的类别/文档**得分份额**聚合，得到"命中目录 + 主文档"，
  通过 `note` 字段暴露（CLI、界面提示、证据文本都会显示），例如
  `路由: 功能详解 · 12-功能详解-小艺慧记会议纪要.md`。
- **目录软加权**：命中块得分 × (1 + `RAG_CATEGORY_BOOST` × 其类别份额)，让主目录的块更靠前、
  抑制跨目录噪声。实测：路由 5/5 正确（慧记→功能详解、车载→设备协同…）；`boost=0.1` 时
  同目录一致性提升且分数反转 ≤5%，故默认 0.1；设 0 可关闭。

> 注：路由与加权**完全基于已召回的块**，不额外调用 API、不改变索引格式（无需重新入库）。

### 优化四：查询别名归一化（同音错字）

用户把"小艺"打成"小易/小忆/小义/小依/小翼/晓艺"时，实测会**两道门控全挂**（关键词不中 +
相似度掉到 0.43~0.55 低于阈值）→ 知识库静默不检索。修法是**确定性的别名表**（不是拼音转换：

- 表：内置 `小易/小忆/小义/小依/小翼/小意/小议/小谊/晓艺 → 小艺`，可用 `RAG_ALIAS_MAP` 覆盖；
- 生效范围：**门控关键词检查 / 查询嵌入 / 检索文本**（BM25、精排）三处；用户消息与证据输出保持原话；
- 开关：`RAG_ALIAS_NORMALIZE`（默认 1，设 0 关闭）。

标定（裸问法 `小X新特性`，9 个变体）：

| 变体 | 关闭归一化 | 开启归一化 |
| - | - | - |
| 小艺（正确） | ✅ 触发 | ✅ 触发 |
| 小易 / 小忆 / 小义 / 小依 / 小翼 / 晓艺 | ❌ 卡在关键词门控（0/6） | ✅ 全部触发（**6/6**，归一化后相似度与正确写法一致 0.580） |
| 小雨 / 小姨（**故意不入表**） | ❌ | ❌ 保持原样 |

> `小雨/小姨` 是真实词汇（"明天小雨""我小姨"），纳入会产生误伤，故默认排除；确需的话用
> `RAG_ALIAS_MAP=小易=小艺,小雨=小艺` 自行追加。
>
> 带上下文的问法（如"小X慧记有什么限制"）**本来就能触发**（8~9/9），归一化是补上"裸名问句"这个静默盲区。

## 与参考项目（xiaoyi_demo）的对应与差异

| 本模块 | 参考项目 |
| - | - |
| `chunking.py` | `app/kb/chunking.py`（langchain → 纯 Python 重写） |
| `documents.py` | `app/kb/documents.py`（语义一致；新增 `source_file`/`file_category`） |
| `localstore.py` | `app/kb/localstore.py`（知识源改为按文件名约定扫描；索引落 `.xiaoyi/`） |
| `embeddings.py` / `rerank.py` | `app/core/embeddings.py` / `app/core/rerank.py` |
| `retrieval.py` | `app/core/retrieval.py` |

**有意未移植**（属"服务/生成"层，不是检索所需）：Query 改写与同义词扩展、
指代消解、置信度闸与语义闸、多查询兜底、聊天生成与 SSE 服务、sqlite 会话存储。
后续要把 RAG 接进 xiaoyi（做成工具或命令）时，这一步再按需补。

## 扩展 / 更新知识库

**一句话：改 `rag/data/*.md` → 跑一次入库 → 把「md 文件 + `rag/index/rag_index.json.gz`」一起提交。**
两者必须成对更新（md 是源、index 是产物），服务器拉取后即可用。

```bash
# 1) 新增/修改文档（命名 NN-类别-标题.md，续号即可，如 31-...、32-...）
#    每份文档有唯一的 `# 一级标题`（作为 category 与引用名）；frontmatter 会被自动剥离
#    新类别需在 sources.py 的 CATEGORY_TYPES 登记，否则 content_type 退化为 "doc"
vim xiaoyi/rag/data/31-功能详解-小艺与第三方应用联动.md

# 2) 入库（检测到文档变化会自动全量重嵌；需联网 + EMBED_API_KEY）
python xiaoyi/rag/build_index.py            # 或 --force 强制重建
#    输出示例：OK 入库完成：共 3xx 块 · 嵌入模型 BAAI/bge-m3 · <时间>

# 3) 验证 + 提交（md 与索引一起提交）
python xiaoyi/rag/query.py "新加的主题" --k 3
git add xiaoyi/rag/data/ xiaoyi/rag/index/
```

**几个容易踩的点**：

| 情况 | 结果 |
| - | - |
| 只加 md、**不重建索引** | 新文档检索不到（宽松模式下只打印"指纹不同"告警，不会报错） |
| 只提交 index、不提交 md | 当前环境能检索到，但别人 clone 后无法重建（缺源文档），且与新内容不一致 |
| 文件名不符合 `NN-类别-标题.md` | 该文件被**静默跳过**，不入库 |
| 索引里已存在旧编号（重号） | 不报错，仅排序并列；建议编号唯一、续号 |
| 换了 `EMBED_MODEL` 或切块参数 | 必须重建（否则宽松模式会告警但仍用旧向量，检索质量下降） |

## 接入 xiaoyi（harness）

`api.py` 是对外薄封装（阈值过滤 + 证据文本化，永不抛异常）：

```python
from xiaoyi.rag import api as rag_api

result = await rag_api.rag_search("小艺慧记有什么限制", k=5)   # status: ok/not_ready/no_evidence/error
if result.status == rag_api.RAG_OK:
    text = rag_api.format_evidence(result.hits)   # 证据文本（小节路径 + 来源文件 + 相关度）
```

> 证据清单**不带编号**：每条以「小节路径（来源: 文件，相关度 x.xx）」开头，并明确要求模型
> 引用时写明小节名或来源文件名、不要输出编号或行号（此前带编号时模型曾编造越界编号 `[6]`
> 与虚构行号 `file.md:28-77`）。

门控原语（供调用方决定是否值得检索）：

```python
rag_api.keyword_hit("怎么换唤醒词")            # ① 关键词/实体（零成本）
sim, vec = await rag_api.embed_and_max_similarity("帮我写个快排")  # ② 相似度（一次嵌入）
rag_api.gate_min_similarity()                  #   阈值（默认 0.55）
await rag_api.rag_search(q, query_vec=vec)     # ③ 检索（复用向量，不再重复嵌入）
```

harness 侧由 `.xiaoyi/config.yaml` 的 `enable_rag` 开关控制，开启后：

- 每轮对话自动预取检索，命中证据以 system-reminder 注入（UI 提示命中条数）；
- 注册 `KnowledgeSearch` 工具（category=read，默认权限模式无需确认）。

## 部署到服务器 / 新机器

索引（`xiaoyi/rag/index/rag_index.json.gz`）**随仓库提交**，克隆/解压后**开箱即用**，
无需在目标机器重新入库：

```bash
# 1) 密钥：.env 不入版本库，需手动准备（检索要用）
cp xiaoyi/rag/.env.example xiaoyi/rag/.env && vi xiaoyi/rag/.env   # 填 EMBED_API_KEY / RERANK_API_KEY

# 2) 直接用（加载本地索引，不联网）
python xiaoyi/rag/query.py "小艺怎么开启语音唤醒" --k 2
```

**指纹与两种校验模式**：索引里记录了源文档指纹（每个 md 的 size + mtime）。
默认**宽松模式**——换机器/克隆后 mtime 变化会导致指纹不一致，此时只打印告警
（`status()["stale"]`）并**照常加载**；设 `RAG_INDEX_STRICT=1` 可切换为严格模式
（任一差异即拒绝加载，必须重新入库），适合对数据新鲜度要求严格的场景。

**什么时候需要重新入库**：改了 `rag/data/*.md` 或换了 `EMBED_MODEL` / 切块参数后，
运行 `python xiaoyi/rag/build_index.py`（联网）并提交更新后的索引文件即可。

## 网络不可达时的自动降级（服务器/内网环境）

检索默认走"在线嵌入（bge-m3）+ 在线精排（bge-reranker）"。当部署环境**不能访问
`api.siliconflow.cn`**（无外网 / 防火墙 / 容器网络限制）时，检索链会自动降级、不会失败：

| 情况 | 行为 | 质量 |
| - | - | - |
| 网络正常 | 向量 + BM25 → RRF → bge 精排（完整链路） | 最好 |
| 嵌入不可达（APIConnectionError/超时） | **纯本地 BM25**（完全离线，零 API） | 可用，无语义匹配/精排 |
| 仅重排不可达 | 向量 + BM25 → RRF（跳过精排） | 较好，按 RRF 顺序 |

- **熔断**：首次失败后 5 分钟内不再尝试联网（避免每轮撞超时），期间查询是毫秒级；
  5 分钟后自动重试；也可重启进程立即恢复。
- **可见性**：降级时结果里会带说明（如"嵌入服务不可达（APIConnectionError: …），
  已降级为本地关键词检索（BM25，不联网）"），界面提示也会显示。
- 想彻底避免降级：让部署环境能出网并在 `.env` 配好两个 KEY（质量最优）。
