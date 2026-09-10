"""本地知识索引：xiaoyi/rag/data/*.md → 切块 → 嵌入，索引全部落本地。

参考 xiaoyi_demo/app/kb/localstore.py，适配点：
- 知识源改为按文件名约定扫描（见 sources.py），不再硬编码白名单；
- 行数据补充 source_file / file_category；
- 索引产物落在 .xiaoyi/rag_index.json.gz（运行时状态目录，自动 gitignore）。

检索纯进程内（本项目 20 份文档 ≈ 226 块，毫秒级）：
  * dense：向量余弦（嵌入文本 = category + questions + answer，与参考项目一致）
  * BM25 ：中文 CJK 二元组 + 英文词/数字分词
  * hybrid：两路各召回后 RRF 融合（k=60，与参考项目同参）
"""
from __future__ import annotations

import sys
from pathlib import Path

# 本文件夹自成一体：把自身目录加入模块搜索路径，直接用绝对名导入同目录模块。
_RAG_DIR = Path(__file__).resolve().parent
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

import array
import base64
import gzip
import json
import logging
import math
import re
import time
from pathlib import Path

import embeddings as rag_embeddings
import config as rag_config
from documents import build_chunks
from sources import list_sources, read_markdown

logger = logging.getLogger(__name__)

_INDEX_VERSION = 1
_RRF_K = 60
_BM25_K1, _BM25_B = 1.5, 0.75

# ---------- 分词与 BM25（纯函数，便于单测） ----------

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_RUN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文段切 CJK 二元组（单字成词时保留单字），英文词/数字整段保留（小写）。"""
    t = (text or "").lower()
    out: list[str] = []
    for run in _CJK_RUN.findall(t):
        if len(run) <= 1:
            out.append(run)
            continue
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
    out.extend(_ASCII_RUN.findall(t))
    return out


def _build_inverted(doc_tokens: list[list[str]]) -> tuple[dict[str, dict[int, int]], dict[str, float]]:
    """(词 → {doc_idx: tf}, 词 → idf)。df 只在 (词, 文档) 首次出现时 +1。"""
    inverted: dict[str, dict[int, int]] = {}
    df: dict[str, int] = {}
    for i, toks in enumerate(doc_tokens):
        seen: set[str] = set()
        for term in toks:
            post = inverted.setdefault(term, {})
            post[i] = post.get(i, 0) + 1
            if term not in seen:
                seen.add(term)
                df[term] = df.get(term, 0) + 1
    n = max(len(doc_tokens), 1)
    idf = {term: math.log(1 + (n - d + 0.5) / (d + 0.5)) for term, d in df.items()}
    return inverted, idf


# ---------- 索引状态（进程内单例） ----------

class IndexNotReady(Exception):
    """索引不可用（未构建 / 构建失败）。message 给用户看。"""


class _IndexState:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.ready = False
        self.error: str | None = None
        self.stale: str = ""          # 宽松模式下记录"索引与当前环境的差异"
        self.built_at: str | None = None
        self.embed_model: str | None = None
        self.files: list[dict] = []
        self.rows: list[dict] = []
        self.vecs: list[list[float]] = []
        self.doc_tokens: list[list[str]] = []
        self.inverted: dict[str, dict[int, int]] = {}
        self.idf: dict[str, float] = {}
        self.avgdl = 0.0

    def _require(self) -> None:
        if not self.ready:
            raise IndexNotReady(
                self.error or "知识索引尚未入库，请先运行 python xiaoyi/rag/build_index.py"
            )

    # ---- 检索 ----

    def _cat_ok(self, row: dict, category: str | None) -> bool:
        return category is None or row["category"] == category

    @staticmethod
    def _normalize(v: list[float]) -> list[float]:
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v] if norm else v

    def dense_top(self, query_vec: list[float], top_k: int, category: str | None) -> list[dict]:
        self._require()
        qv = self._normalize(query_vec)
        scored: list[tuple[float, int]] = []
        for i, row in enumerate(self.rows):
            if not self._cat_ok(row, category):
                continue
            scored.append((sum(a * b for a, b in zip(qv, self.vecs[i])), i))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [self._hit(i, s) for s, i in scored[:top_k]]

    def bm25_top(self, text: str, top_k: int, category: str | None) -> list[dict]:
        self._require()
        terms = list(dict.fromkeys(t for t in tokenize(text) if t in self.idf))
        if not terms:
            return []
        per_doc: dict[int, float] = {}
        for term in terms:
            post = self.inverted.get(term)
            if not post:
                continue
            idf = self.idf[term]
            for doc_idx, tf in post.items():
                if not self._cat_ok(self.rows[doc_idx], category):
                    continue
                dl = len(self.doc_tokens[doc_idx]) or 1
                denom = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / (self.avgdl or 1))
                per_doc[doc_idx] = per_doc.get(doc_idx, 0.0) + idf * tf * (_BM25_K1 + 1) / denom
        ranked = sorted(per_doc.items(), key=lambda x: x[1], reverse=True)
        return [self._hit(i, s) for i, s in ranked[:top_k]]

    def hybrid_top(self, query_vec: list[float], text: str, top_k: int,
                   recall_k: int, category: str | None) -> list[dict]:
        """dense / BM25 各召回 recall_k 条，RRF 融合（k=60）后取 top_k。"""
        self._require()
        dense = self.dense_top(query_vec, recall_k, category)
        bm25 = self.bm25_top(text, recall_k, category)
        rrf: dict[int, float] = {}
        for rank, hit in enumerate(dense, start=1):
            rrf[hit["id"]] = rrf.get(hit["id"], 0.0) + 1.0 / (_RRF_K + rank)
        for rank, hit in enumerate(bm25, start=1):
            rrf[hit["id"]] = rrf.get(hit["id"], 0.0) + 1.0 / (_RRF_K + rank)
        order = sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:top_k]
        by_id = {h["id"]: h for h in [*dense, *bm25]}
        out = []
        for cid, score in order:
            hit = dict(by_id[cid])
            hit["score"] = score
            out.append(hit)
        return out

    def _hit(self, i: int, score: float) -> dict:
        row = self.rows[i]
        return {
            "id": row["id"], "score": round(float(score), 4),
            "question": row["questions"], "answer": row["answer"],
            "section_path": row["section_path"], "content_type": row["content_type"],
            "category": row["category"], "source_file": row.get("source_file", ""),
        }

    def count(self) -> int:
        return len(self.rows)


_state = _IndexState()


def state() -> _IndexState:
    """暴露单例状态（检索层 / CLI 用）。"""
    return _state


def reset_for_tests() -> None:
    _state.reset()


# ---------- 构建与加载 ----------

def _source_fingerprints() -> dict[str, list]:
    return {s.name: [s.path.stat().st_size, s.path.stat().st_mtime_ns]
            for s in list_sources() if s.path.exists()}


def _rows_payload() -> dict:
    return {
        "version": _INDEX_VERSION,
        "built_at": _state.built_at,
        "embed_model": _state.embed_model,
        "docs": _source_fingerprints(),
        "chunk_size": rag_config.settings.chunk_size,
        "chunk_overlap": rag_config.settings.chunk_overlap,
        "files": _state.files,
        "chunks": _state.rows,
        "vectors": _pack_vecs(_state.vecs),
    }


def _pack_vecs(vecs: list[list[float]]) -> list[str]:
    return [base64.b64encode(array.array("f", v).tobytes()).decode() for v in vecs]


def _unpack_vecs(blobs: list[str]) -> list[list[float]]:
    return [list(array.array("f", base64.b64decode(b))) for b in blobs]


def _save() -> None:
    path = Path(rag_config.settings.index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(_rows_payload(), f, ensure_ascii=False)


def _load_cached() -> bool:
    """加载本地索引缓存。

    默认**宽松模式**：只有格式版本不符才拒绝；嵌入模型 / 切块参数 / 源文档指纹与当前
    环境有差异时仅记录告警（`status()["stale"]`）并照常加载——索引随仓库上传后开箱即用。
    设置 RAG_INDEX_STRICT=1 切到严格模式：任一差异即判定失效，要求重新入库。
    """
    path = Path(rag_config.settings.index_path)
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("version") != _INDEX_VERSION:
        return False

    stale_reasons: list[str] = []
    if data.get("embed_model") != rag_config.settings.embed_model:
        stale_reasons.append(
            f"嵌入模型不同（索引 {data.get('embed_model')} ≠ 当前 {rag_config.settings.embed_model}）"
        )
    if (data.get("chunk_size") != rag_config.settings.chunk_size
            or data.get("chunk_overlap") != rag_config.settings.chunk_overlap):
        stale_reasons.append("切块参数不同")
    if data.get("docs") != _source_fingerprints():
        stale_reasons.append("源文档指纹不同（文档有改动，或换机器后文件时间戳变化）")

    if stale_reasons:
        if rag_config.settings.index_strict:
            _state.reset()
            _state.error = ("索引与当前环境不一致（" + "；".join(stale_reasons) + "）："
                            "严格模式（RAG_INDEX_STRICT=1）下需重新入库 "
                            "python xiaoyi/rag/build_index.py")
            return False
        _state.stale = "；".join(stale_reasons)
        logger.warning("索引与当前环境存在差异，宽松模式继续加载：%s（如需精确请重新入库）",
                       _state.stale)

    _state.ready = True
    _state.error = None
    _state.built_at = data["built_at"]
    _state.embed_model = data["embed_model"]
    _state.files = data["files"]
    _state.rows = data["chunks"]
    _state.vecs = [_state._normalize(v) for v in _unpack_vecs(data["vectors"])]
    _index_bm25()
    logger.info("本地索引从缓存加载: %d 块, %s", len(_state.rows), _state.built_at)
    return True


def _index_bm25() -> None:
    texts = [f"{r['category']}\n{r['questions']}\n{r['answer']}" for r in _state.rows]
    _state.doc_tokens = [tokenize(t) for t in texts]
    _state.inverted, _state.idf = _build_inverted(_state.doc_tokens)
    lens = [len(t) for t in _state.doc_tokens]
    _state.avgdl = sum(lens) / len(lens) if lens else 0.0


def _build_rows() -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    files: list[dict] = []
    cid = 1
    for src in list_sources():
        if not src.path.exists():
            logger.warning("源文档缺失，跳过: %s", src.name)
            continue
        md = read_markdown(src)
        chunks = build_chunks(
            md,
            content_type=src.content_type,
            source_file=src.name,
            file_category=src.file_category,
            chunk_size=rag_config.settings.chunk_size,
            overlap=rag_config.settings.chunk_overlap,
            table_max_rows=rag_config.settings.table_max_rows,
        )
        for c in chunks:
            rows.append({
                "id": cid, "category": c.category, "questions": c.questions,
                "answer": c.answer, "section_path": c.section_path,
                "content_type": c.content_type, "is_key_clause": c.is_key_clause,
                "source_file": c.source_file, "file_category": c.file_category,
            })
            cid += 1
        files.append({
            "name": src.name, "content_type": src.content_type,
            "file_category": src.file_category, "chunks": len(chunks),
            "size": src.path.stat().st_size,
        })
    return rows, files


async def build(force: bool = False) -> dict:
    """从 data/*.md 建索引并持久化；force=True 无视缓存重建。"""
    if not force and _state.ready:
        return {"status": "ready", "chunks": _state.count(),
                "built_at": _state.built_at, "files": _state.files}

    rows, files = _build_rows()
    if not rows:
        raise IndexNotReady(f"{rag_config.settings.kb_dir} 下没有可入库文档（文件名需形如 NN-类别-标题.md）")

    texts = [f"{r['category']}\n{r['questions']}\n{r['answer']}" for r in rows]
    vecs: list[list[float]] = []
    try:
        for i in range(0, len(texts), rag_config.settings.embed_batch):
            vecs.extend(await rag_embeddings.embed_texts(texts[i:i + rag_config.settings.embed_batch]))
    except Exception as e:
        _state.reset()
        _state.error = f"嵌入上游调用失败，索引未建成：{type(e).__name__}: {e}"
        logger.error(_state.error)
        raise IndexNotReady(_state.error) from e
    if len(vecs) != len(rows):
        _state.reset()
        _state.error = "嵌入返回条数与 chunk 数不一致，索引未建成"
        raise IndexNotReady(_state.error)

    _state.ready = True
    _state.error = None
    _state.built_at = time.strftime("%Y-%m-%d %H:%M:%S")
    _state.embed_model = rag_config.settings.embed_model
    _state.files = files
    _state.rows = rows
    _state.vecs = [_state._normalize(v) for v in vecs]
    _index_bm25()
    try:
        _save()
    except OSError as e:
        logger.warning("索引持久化失败（不影响内存检索）: %s", e)
    logger.info("知识索引构建完成: %d 块", len(rows))
    return {"status": "built", "chunks": len(rows), "built_at": _state.built_at, "files": files}


def load() -> bool:
    """启动加载：只读本地缓存，绝不联网。未命中时状态里记下原因。"""
    if _state.ready:
        return True
    if _load_cached():
        return True
    path = Path(rag_config.settings.index_path)
    if not path.exists():
        _state.error = ("知识索引不存在：索引是本地产物、不入版本库，换机器/部署到服务器后"
                        "需要在当前环境重新入库 python xiaoyi/rag/build_index.py"
                        "（需 xiaoyi/rag/.env 的 EMBED_API_KEY）")
    else:
        _state.error = ("索引缓存与源文档不一致（文档有改动 / 换过嵌入模型 / 换机器后"
                        "文件时间戳变化）：请重新入库 python xiaoyi/rag/build_index.py")
    return False


def status() -> dict:
    """状态概览：就绪与否 / 文档与块数 / 构建信息 / 错误。不抛异常。"""
    return {
        "ready": _state.ready,
        "error": _state.error,
        "stale": _state.stale,
        "built_at": _state.built_at,
        "embed_model": _state.embed_model,
        "chunk_total": _state.count(),
        "index_path": str(rag_config.settings.index_path),
        "files": _state.files or [
            {"name": s.name, "content_type": s.content_type,
             "file_category": s.file_category,
             "size": s.path.stat().st_size}
            for s in list_sources() if s.path.exists()
        ],
    }
