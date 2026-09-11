"""RAG 检索薄封装：给 harness（或其它调用方）用的稳定入口。

- ``rag_search(query, k, min_score)``：检索 + rerank 分数阈值过滤；
  **永不抛异常**——索引未就绪 / 上游失败都以状态返回，便于调用方静默降级；
- ``format_evidence(hits)``：把命中块编排成可注入的文本（带 [n] 编号与出处）。
"""
from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 本文件夹自成一体：把自身目录加入模块搜索路径，直接用绝对名导入同目录模块。
_RAG_DIR = Path(__file__).resolve().parent
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

import config as rag_config
import embeddings as rag_embeddings
import health
import localstore as rag_store
import sources as rag_sources
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
    note: str = ""            # 说明（目录路由 / 降级 / 去重合并），正常时含路由信息
    route_category: str = ""  # 目录路由：命中的文档类别（如"功能详解"）
    route_source: str = ""    # 目录路由：命中的主文档（文件名）

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
    search_query = normalize_query(query)   # 错字归一化后用于检索；原话保留在 query 里

    if not rag_store.load():          # 只读本地索引，不联网
        return RagResult(
            RAG_NOT_READY,
            query=query,
            message=rag_store.status().get("error") or "知识索引未就绪",
        )

    k = k or rag_config.settings.rerank_top_k
    try:
        hits = await search_knowledge(search_query, top_k=k, query_vec=query_vec)
    except Exception as e:            # 上游失败不炸调用方
        return RagResult(RAG_ERROR, query=query, message=f"{type(e).__name__}: {e}")

    # 注入去重：同一事实来自多篇文档 / 同文档表格重切 → 只保留分数最高的一条
    hits, merged = _dedupe_hits(hits)

    # 目录路由 + 软加权（份额来自已召回块，零额外 API 调用）
    hits, route_cat, route_src, route_share = _route_and_boost(
        hits, rag_config.settings.category_boost
    )

    notes: list[str] = []
    if route_cat:
        notes.append(f"目录：{route_cat}" + (f"（{route_share:.0%}）" if route_share else ""))
    if health.note():
        notes.append(health.note())   # 降级说明（正常为空）
    if merged:
        notes.append(f"已合并 {merged} 条重复证据")
    note = "；".join(notes)
    if not hits:
        return RagResult(RAG_NO_EVIDENCE, query=query, message=note or "未召回任何块", note=note)

    # 阈值过滤只在完整链路（有 rerank 分数）下生效；降级结果没有可比分数，直接返回
    if health.mode() == "full":
        threshold = (
            rag_config.settings.rerank_min_score if min_score is None else float(min_score)
        )
        kept = [h for h in hits if float(h.get("rerank_score", 0.0)) >= threshold]
        if not kept:
            return RagResult(
                RAG_NO_EVIDENCE,
                query=query,
                message=f"检索到 {len(hits)} 条，均低于阈值 {threshold:.2f}",
                route_category=route_cat,
                route_source=route_src,
            )
    else:
        kept = hits[:k]

    used = health.mode()
    msg = f"命中 {len(kept)} 条" + (f"（降级：{used}）" if used != "full" else "")
    return RagResult(
        RAG_OK, query=query, hits=kept, message=msg, note=note,
        route_category=route_cat, route_source=route_src,
    )


def format_evidence(hits: list[dict], max_answer_chars: int = 1200, note: str = "") -> str:
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
    ]
    if note:
        lines.append(f"（检索说明：{note}）")
        lines.append("")
    lines += [
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


# ---------------------------------------------------------------- 注入去重
# 同一事实常出现在多篇文档里（如"能力全景"与"专题详解"都写同一组设置），
# 或在同文档内被表格切分重复。用"长片段重合率"判定是否同一事实：
# 归一化（去空白与标记符号）后取 12 字滑窗，共享片段数 / 较短文本片段数。
_DEDUPE_NGRAM = 12
_DEDUPE_STRIP_RE = re.compile(r"[\s*|#>`\-—+>（）()【】\[\]{}、，。！？；：,.!?;:\"']+")


def _normalize_for_overlap(text: str) -> str:
    return _DEDUPE_STRIP_RE.sub("", text or "")


def _overlap_ratio(a: str, b: str) -> float:
    A = _normalize_for_overlap(a)
    B = _normalize_for_overlap(b)
    n = _DEDUPE_NGRAM
    if len(A) < n or len(B) < n:
        return 0.0
    ga = {A[i:i + n] for i in range(len(A) - n + 1)}
    gb = {B[i:i + n] for i in range(len(B) - n + 1)}
    return len(ga & gb) / min(len(ga), len(gb))


def _route_and_boost(
    hits: list[dict], boost: float
) -> tuple[list[dict], str, str, float]:
    """目录路由 + 软加权。

    按命中块所属类别/文档的**得分份额**聚合，得到"命中的目录与主文档"；
    再让各块得分 × (1 + boost × 其类别份额) 后重排——份额大的类别整体占优，
    从而抑制跨目录噪声（份额数据完全来自已召回的块，不额外调 API）。
    返回 (重排后的 hits, 主类别, 主文档, 主类别份额)。
    """
    if not hits:
        return hits, "", "", 0.0

    def score_of(h: dict) -> float:
        return max(float(h.get("rerank_score", h.get("score", 0.0)) or 0.0), 0.0)

    total = sum(score_of(h) for h in hits) or 1.0
    cat_weight: dict[str, float] = {}
    src_weight: dict[str, float] = {}
    for h in hits:
        w = score_of(h)
        cat_weight[h.get("file_category", "")] = cat_weight.get(h.get("file_category", ""), 0.0) + w
        src_weight[h.get("source_file", "")] = src_weight.get(h.get("source_file", ""), 0.0) + w

    top_cat = max(cat_weight, key=cat_weight.get)
    top_src = max(src_weight, key=src_weight.get)
    cat_share = {c: w / total for c, w in cat_weight.items()}
    top_share = cat_share[top_cat]

    if boost:
        for h in hits:
            share = cat_share.get(h.get("file_category", ""), 0.0)
            h["rank_score"] = score_of(h) * (1.0 + boost * share)
        hits = sorted(hits, key=lambda h: h["rank_score"], reverse=True)
    return hits, top_cat, top_src, top_share


def _dedupe_hits(hits: list[dict], min_overlap: float | None = None) -> tuple[list[dict], int]:
    """同源/近重去重：按分数序扫描，与已保留块重合率超阈值者丢弃。

    返回 (去重后列表, 丢弃条数)。阈值默认取 rag/.env 的 RAG_DEDUPE_MIN_OVERLAP（0.10）。
    """
    threshold = (
        rag_config.settings.dedupe_min_overlap if min_overlap is None else float(min_overlap)
    )
    kept: list[dict] = []
    for hit in hits:
        answer = hit.get("answer", "")
        if any(_overlap_ratio(answer, k.get("answer", "")) >= threshold for k in kept):
            continue
        kept.append(hit)
    return kept, len(hits) - len(kept)


# ---------------------------------------------------------------- 门控原语
# 调用方（如 harness）据此决定"这条消息值不值得查知识库"，避免每轮都付
# 嵌入 + 重排的代价。三层门控：① 关键词/实体（本函数，零成本）
# ② 相似度（embed_and_max_similarity，一次嵌入 + 本地点积）
# ③ 重排分数阈值（rag_search 内部已有）。


def normalize_query(text: str) -> str:
    """查询别名归一化：把常见同音错字替换为正确写法（如"小易"→"小艺"）。

    - 只做确定性替换（表来自 rag/.env 的 RAG_ALIAS_MAP，内置一份小表），不引入拼音依赖；
    - 长词优先（避免"晓艺"被"艺"这类短词提前匹配）；
    - 仅用于**门控判断 / 嵌入 / 检索文本**；用户的原始消息与证据输出保持原样。
    """
    if not text or not rag_config.settings.alias_normalize:
        return text
    alias = rag_config.settings.alias_map
    if not alias:
        return text
    for wrong in sorted(alias, key=len, reverse=True):
        right = alias[wrong]
        if wrong and wrong != right and wrong in text:
            text = text.replace(wrong, right)
    return text


def keyword_hit(text: str) -> bool:
    """域内关键词/实体门控：命中任一关键词即视为"与知识库相关"。

    词表默认覆盖小艺/鸿蒙相关术语，可用 rag/.env 的 RAG_GATE_KEYWORDS 覆盖。
    """
    t = normalize_query(text).lower()
    if not t:
        return False
    return any(k.lower() in t for k in rag_sources.gate_keywords())


def gate_min_similarity() -> float:
    """相似度门控阈值（默认 0.55，可经 RAG_GATE_MIN_SIMILARITY 调整）。"""
    return float(rag_config.settings.gate_min_similarity)


async def embed_and_max_similarity(query: str) -> tuple[float, list[float]]:
    """嵌入查询并与索引向量算最大余弦（本地，毫秒级）。

    返回 (最高相似度, 归一化查询向量)：向量可直接传给 ``rag_search(query_vec=…)``，
    让门控与检索共用同一次嵌入。索引未就绪或上游失败时返回 (-1.0, [])，
    调用方据此跳过（绝不抛异常）。
    """
    query = normalize_query((query or "").strip())
    if not query:
        return -1.0, []
    if not rag_store.load():
        return -1.0, []
    if not health.embed_available():
        return -1.0, []           # 熔断期内不再尝试（避免每轮撞超时）
    try:
        vec = await rag_embeddings.embed_query(query)
    except Exception as e:
        health.mark_embed_down(e)
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
