"""KnowledgeSearch 工具：检索本地小艺知识库（RAG）。

链路：bge 向量 + BM25 混合召回 → RRF → bge-reranker 精排（见 xiaoyi/rag/）。
仅只读查询（category="read"），默认权限模式下无需确认；
rag 模块按需懒加载——未启用/未入库/上游异常都不会影响 harness 启动与其它对话。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from xiaoyi.tools.base import Tool, ToolResult

_NOT_READY_HINT = "（请先在项目根目录运行 python xiaoyi/rag/build_index.py 入库）"


class KnowledgeSearchParams(BaseModel):
    query: str
    k: int = 5


class KnowledgeSearchTool(Tool):
    name = "KnowledgeSearch"
    description = (
        "检索本地小艺知识库（离线 RAG：向量 + BM25 混合召回 + bge 精排）。"
        "当问题涉及华为小艺 / 鸿蒙 / 小艺帮记、小艺慧记、小艺通话、隐私与版本要求等"
        "内容时，优先用它拿到带出处的证据段落再作答；返回内容含 [n] 编号与来源文件。"
    )
    params_model = KnowledgeSearchParams
    category = "read"

    async def execute(self, params: BaseModel) -> ToolResult:
        assert isinstance(params, KnowledgeSearchParams)

        try:
            from xiaoyi.rag import api as rag_api
        except Exception as e:  # rag 未部署/依赖缺失：不影响主流程
            return ToolResult(
                output=f"知识库不可用（{type(e).__name__}: {e}）", is_error=True
            )

        result = await rag_api.rag_search(params.query, k=params.k)

        if result.status == rag_api.RAG_OK:
            return ToolResult(output=rag_api.format_evidence(result.hits, note=result.note))
        if result.status == rag_api.RAG_NOT_READY:
            return ToolResult(output=f"知识库未就绪：{result.message}{_NOT_READY_HINT}")
        if result.status == rag_api.RAG_NO_EVIDENCE:
            return ToolResult(output=f"知识库中没有足够相关的证据：{result.message}")
        return ToolResult(output=f"知识库检索失败：{result.message}", is_error=True)

    def get_schema(self) -> dict[str, Any]:
        return super().get_schema()
