"""RAG 配置：读取 xiaoyi/rag/.env（环境变量优先，便于临时覆盖）。

键名与 xiaoyi_demo 保持一致（EMBED_* / RERANK_* / KNOWLEDGE_* / RECALL_TOP_K …），
方便两边配置对照；也接受少量别名。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parent          # xiaoyi/rag/
PROJECT_ROOT = RAG_DIR.parent.parent               # 项目根
DATA_DIR = RAG_DIR / "data"                        # 知识源（20 份 md）
ENV_FILE = RAG_DIR / ".env"
INDEX_PATH = RAG_DIR / "index" / "rag_index.json.gz"   # 随仓库提交，部署即可用


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载：KEY=VALUE，忽略注释与空行；不覆盖已存在的环境变量。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(ENV_FILE)


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _env_int(*names: str, default: int) -> int:
    try:
        return int(_env(*names, default=str(default)))
    except ValueError:
        return default


def _env_bool(*names: str, default: bool) -> bool:
    value = _env(*names, default="")
    if not value:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_float(*names: str, default: float) -> float:
    try:
        return float(_env(*names, default=str(default)))
    except ValueError:
        return default


# 域内关键词/实体（门控第 1 层）。问小艺相关问题时通常会出现这些词；
# 可用 rag/.env 的 RAG_GATE_KEYWORDS（英文逗号分隔）整体覆盖。
DEFAULT_GATE_KEYWORDS: tuple[str, ...] = (
    "小艺", "鸿蒙", "harmonyos", "harmony os", "智慧助手",
    "慧记", "帮记", "帮写", "小艺通话", "小艺字幕", "小艺建议", "小艺修图", "小艺看世界",
    "唤醒词", "语音唤醒", "通话摘要", "盘古", "hmaf", "智能体广场", "小艺开放平台",
    "腕上", "车载小艺", "全屋智能", "小艺帮接",
)


def _parse_keywords(raw: str) -> tuple[str, ...]:
    if not raw.strip():
        return DEFAULT_GATE_KEYWORDS
    items = tuple(k.strip() for k in raw.split(",") if k.strip())
    return items or DEFAULT_GATE_KEYWORDS


@dataclass
class Settings:
    # ---- 嵌入：bge-m3（入库时构建索引） ----
    embed_base_url: str = field(default_factory=lambda: _env(
        "EMBED_BASE_URL", "KNOWLEDGE_EMBEDDING_BASE_URL",
        default="https://api.siliconflow.cn/v1"))
    embed_model: str = field(default_factory=lambda: _env(
        "EMBED_MODEL", "KNOWLEDGE_EMBEDDING_MODEL", default="BAAI/bge-m3"))
    embed_api_key: str = field(default_factory=lambda: _env(
        "EMBED_API_KEY", "SILICONFLOW_API_KEY"))

    # ---- 重排：bge-reranker-v2-m3（检索后精排） ----
    rerank_base_url: str = field(default_factory=lambda: _env(
        "RERANK_BASE_URL", "KNOWLEDGE_EMBEDDING_BASE_URL",
        default="https://api.siliconflow.cn/v1"))
    rerank_model: str = field(default_factory=lambda: _env(
        "RERANK_MODEL", default="BAAI/bge-reranker-v2-m3"))
    rerank_api_key: str = field(default_factory=lambda: _env(
        "RERANK_API_KEY", "SILICONFLOW_API_KEY"))

    # ---- 检索（三档条数，对应：召回 → RRF 候选池 → 精排） ----
    recall_top_k: int = field(default_factory=lambda: _env_int(
        "RECALL_TOP_K", "KNOWLEDGE_RECALL_K", default=10))
    candidate_top_k: int = field(default_factory=lambda: _env_int(
        "CANDIDATE_TOP_K", "KNOWLEDGE_CANDIDATE_TOP_K", default=10))
    rerank_top_k: int = field(default_factory=lambda: _env_int(
        "KNOWLEDGE_TOP_K", "RERANK_TOP_K", default=5))
    # 重排分数阈值（门控第 3 层）：最高分低于它 → 视为证据不足，不注入
    rerank_min_score: float = field(default_factory=lambda: _env_float(
        "RERANK_MIN_SCORE", default=0.3))
    subquery_split: bool = field(default_factory=lambda: _env_bool(
        "SUBQUERY_SPLIT", default=True))

    # ---- 门控（避免每轮都做检索） ----
    # 相似度门控阈值：查询向量与知识库的最大余弦低于它 → 判定与知识库无关，跳过重排。
    # 实测参考：域内问题 ≥0.6，无关问题多 ≤0.5（详见 README）。
    gate_min_similarity: float = field(default_factory=lambda: _env_float(
        "RAG_GATE_MIN_SIMILARITY", default=0.55))
    gate_keywords: tuple[str, ...] = field(default_factory=lambda: _parse_keywords(
        _env("RAG_GATE_KEYWORDS")))

    # ---- 入库切块 ----
    chunk_size: int = field(default_factory=lambda: _env_int(
        "KNOWLEDGE_CHUNK_SIZE", "KB_CHUNK_SIZE", default=500))
    chunk_overlap: int = field(default_factory=lambda: _env_int(
        "KNOWLEDGE_CHUNK_OVERLAP", "KB_CHUNK_OVERLAP", default=100))
    table_max_rows: int = 10          # 大表格每块最多数据行（超出重贴表头切分）
    embed_batch: int = 64             # 单次嵌入请求的条数

    # ---- 路径 ----
    kb_dir: Path = DATA_DIR
    index_path: Path = field(default_factory=lambda: Path(_env("RAG_INDEX_PATH", default=str(INDEX_PATH))))

    # 索引校验严格模式：默认 False（宽松）——嵌入模型/切块参数/源文档指纹不一致时
    # 只告警、仍然加载，方便"索引随仓库上传后开箱即用"；设为 true 则不一致即判定失效、
    # 必须重新入库（适合对数据新鲜度要求严格的场景）。
    index_strict: bool = field(default_factory=lambda: _env_bool("RAG_INDEX_STRICT", default=False))


settings = Settings()
