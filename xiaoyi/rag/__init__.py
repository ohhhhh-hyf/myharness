"""xiaoyi.rag —— 离线 RAG 知识库（入库 / 检索）。

参考 xiaoyi_demo 的做法实现，但收敛为本项目形态：
- 知识源：xiaoyi/rag/data/*.md（按 md 层级切块，标题路径 → 结构化字段）；
- 嵌入：bge-m3（OpenAI 兼容端点）；重排：bge-reranker-v2-m3（/rerank 端点）；
- 检索：本地索引（向量余弦 + BM25(CJK 二元组) + RRF 融合）；
- 配置：xiaoyi/rag/.env（见 .env.example）；
- 产物：.xiaoyi/rag_index.json.gz（运行时状态目录，不入库）。

本包不引入额外依赖（只用项目已有的 openai / httpx）：
切块逻辑由 xiaoyi_demo 的 langchain 版移植为纯 Python 实现。
"""
