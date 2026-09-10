"""RAG 检索薄封装：给 harness（或其它调用方）用的稳定入口。

- ``rag_search(query, k, min_score)``：检索 + rerank 分数阈值过滤；
  **永不抛异常**——索引未就绪 / 上游失败都以状态返回，便于调用方静默降级；
- ``format_evidence(hits)``：把命中块编排成可注入的文本（带 [n] 编号与出处）。
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 本文件夹自成一体：把自身目录加入模块搜索路径，直接用绝对名导入同目录模块。
_RAG_DIR = Path(__file__).resolve().parent
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

import config as rag_config
import embeddings as rag_embeddings
import localstore as rag_store
from retrieval import search_knowledge

# 状态取值：
#   ok         命中且通过阈值
#   not_ready  索引不存在 / 与源文档不一致（需要先入库）
#   no_evidence 检索到了但全部低于阈值（或空查询）
#   error      嵌入 / 重排上游失败
RAG_OK = "ok"
RAG_NOT_READY = "not_ready"
RAG_NO_EVIDENCE = "no_evidence"
RAG_ERROR = "error"


@dataclass
class RagResult:
    status: str
    query: str = ""
    hits: list[dict] = field(default_factory=list)
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == RAG_OK

    @property
    def top_score(self) -> float:
        return float(self.hits[0].get("rerank_score", 0.0)) if self.hits else 0.0


async def rag_search(
    query: str,
    k: int | None = None,
    min_score: float | None = None,
    query_vec: list[float] | None = None,
) -> RagResult:
    """混合检索（向量 + BM25 → RRF → bge 精排）并按分数阈值过滤。

    k         返回条数（默认取 rag/.env 的 KNOWLEDGE_TOP_K）；
    min_score 最低 rerank 分数（默认取 rag/.env 的 rerank_min_score，0.3）；
    query_vec 预先算好的查询向量（门控第 2 层已经嵌入过时传入，省一次 API 调用）。
    """
    query = (query or "").strip()
    if not query:
        return RagResult(RAG_NO_EVIDENCE, message="空查询")

    if not rag_store.load():          # 只读本地索引，不联网
        return RagResult(
            RAG_NOT_READY,
            query=query,
            message=rag_store.status().get("error") or "知识索引未就绪",
        )

    try:
        hits = await search_knowledge(
            query, top_k=k or rag_config.settings.rerank_top_k, query_vec=query_vec
        )
    except Exception as e:            # 上游失败不炸调用方
        return RagResult(RAG_ERROR, query=query, message=f"{type(e).__name__}: {e}")

    threshold = (
        rag_config.settings.rerank_min_score if min_score is None else float(min_score)
    )
    kept = [h for h in hits if float(h.get("rerank_score", 0.0)) >= threshold]
    if not kept:
        return RagResult(
            RAG_NO_EVIDENCE,
            query=query,
            message=f"检索到 {len(hits)} 条，均低于阈值 {threshold:.2f}",
        )
    return RagResult(RAG_OK, query=query, hits=kept, message=f"命中 {len(kept)} 条")


def format_evidence(hits: list[dict], max_answer_chars: int = 1200) -> str:
    """把命中块编排成注入/工具输出用文本（不带编号）。

    每条以「小节路径（来源: 文件，相关度 x.xx）」开头，并附引用要求：
    说明小节名或来源文件名即可，不要输出编号或行号。
    """
    if not hits:
        return ""
    n = len(hits)
    lines = [
        f"以下内容来自本地小艺知识库的检索结果（共 {n} 条）：",
        "",
        "引用要求：引用时说明小节名或来源文件名即可（例如「据《小艺慧记：会议纪要与实时转写》」），"
        "不要输出编号、行号等本清单未提供的信息；与问题无关的条目直接忽略。",
        "",
    ]
    for h in hits:
        answer = (h.get("answer") or "").strip()
        if len(answer) > max_answer_chars:
            answer = answer[:max_answer_chars] + "…"
        score = float(h.get("rerank_score", 0.0))
        lines.append(
            f"— {h.get('section_path', '')}"
            f"（来源: {h.get('source_file', '')}，相关度 {score:.2f}）"
        )
        lines.append(answer)
        lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- 门控原语
# 调用方（如 harness）据此决定"这条消息值不值得查知识库"，避免每轮都付
# 嵌入 + 重排的代价。三层门控：① 关键词/实体（本函数，零成本）
# ② 相似度（embed_and_max_similarity，一次嵌入 + 本地点积）
# ③ 重排分数阈值（rag_search 内部已有）。


def keyword_hit(text: str) -> bool:
    """域内关键词/实体门控：命中任一关键词即视为"与知识库相关"。

    词表默认覆盖小艺/鸿蒙相关术语，可用 rag/.env 的 RAG_GATE_KEYWORDS 覆盖。
    """
    t = (text or "").lower()
    if not t:
        return False
    return any(k.lower() in t for k in rag_config.settings.gate_keywords)


def gate_min_similarity() -> float:
    """相似度门控阈值（默认 0.55，可经 RAG_GATE_MIN_SIMILARITY 调整）。"""
    return float(rag_config.settings.gate_min_similarity)


async def embed_and_max_similarity(query: str) -> tuple[float, list[float]]:
    """嵌入查询并与索引向量算最大余弦（本地，毫秒级）。

    返回 (最高相似度, 归一化查询向量)：向量可直接传给 ``rag_search(query_vec=…)``，
    让门控与检索共用同一次嵌入。索引未就绪或上游失败时返回 (-1.0, [])，
    调用方据此跳过（绝不抛异常）。
    """
    query = (query or "").strip()
    if not query:
        return -1.0, []
    if not rag_store.load():
        return -1.0, []
    try:
        vec = await rag_embeddings.embed_query(query)
    except Exception:
        return -1.0, []
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    vec = [x / norm for x in vec]
    best = -1.0
    for other in rag_store.state().vecs:
        score = 0.0
        for a, b in zip(vec, other):
            score += a * b
        if score > best:
            best = score
    return float(best), vec
