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

# 2) 入库：data/*.md → 切块 + 嵌入 → .xiaoyi/rag_index.json.gz
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
| 切块 | `KNOWLEDGE_CHUNK_SIZE` / `KNOWLEDGE_CHUNK_OVERLAP` | 默认 500 / 100（改动会触发重新入库） |

## 检索流水线

```
query ──┬─ 子句拆分（一问多意图，如「…，另外…」）
        │
        ├─ 每子句：dense 余弦 Top-N  ＋  本地 BM25 Top-N  → RRF 融合(k=60) → 候选池
        │
        └─ bge-reranker 精排 → Top-K（含 rerank_score）
              ↓
        轮转合并（同小节去重）→ arrange_head_tail 防 lost-in-the-middle（生成侧使用）
```

## 索引与失效规则

- 产物：`.xiaoyi/rag_index.json.gz`（运行时状态目录，已在 .gitignore）；
  内容 = chunk 元数据 + float32 打包 base64 的归一化向量（30 份文档 ≈ 285 块 ≈ 1.0MB）；
- **缓存命中条件**（任一不符即要求重建）：索引版本、`EMBED_MODEL`、切块参数、
  以及全部源文件的 `size + mtime_ns` 指纹；
- **入库与检索解耦**：`query.py`/后续服务启动只读本地索引、不联网；
  仅 `build_index.py` 会调用嵌入接口。

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

## 更新知识库

1. 增删改 `rag/data/*.md`（文件名保持 `NN-类别-标题.md`；新增类别需在
   `sources.py` 的 `CATEGORY_TYPES` 登记）；
2. `python xiaoyi/rag/build_index.py`（检测到文档变化会自动重建）；
3. 检索侧无需改动——下次调用自动加载新索引。

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
