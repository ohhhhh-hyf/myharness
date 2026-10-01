"""请求 notes 域 graph（笔记知识图谱）接口并解析返回字段。用法：python graph.py

统一入口：POST /api/agent/v1，域与任务名在请求体（"domain": "notes", "task": "graph"）。

graph 必填：X-User-Id + docs（data/{USER_ID}/docs/ 下的笔记 .txt/.md 文件）。
docs 也支持图片/其它文档：图片会先走「OCR + LLM 整理审校」生成 md 再直接解析图谱
（不经知识库入库，耗时较长）；非图片文档按正文预览并入。
extra.subject 用于按用户+学科做图谱增量合并（空则视为新学科重建）。
产物：交互式 graph.html（Cytoscape.js 自包含单文件；无 md 落盘，正文在 data.text）。
"""
import os
import uuid

import requests

# ── 笔记文件（须已存在于 data/{USER_ID}/docs/ 下；本样例为「高等数学·极限」语料）──

BASE_URL = os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
URL = f"{BASE_URL}/api/agent/v1"
USER_ID = "1"
DOCS = ["seq_two.txt"]
SUBJECT = "高数"

resp = requests.post(
    URL,
    json={
        "domain": "notes",
        "task": "graph",
        "time": "",
        "texts": {
            "transcript": "",
            "keypoints": "",
            "notes": "",
        },
        "docs": DOCS,
        "memory": True,
        "extra": {
            "template": "",
            "profile": "",
            "project": "",
            "subject": SUBJECT,
            "style": "",
            "memory": True,
        },
    },
    headers={"X-Request-Id": uuid.uuid4().hex, "X-User-Id": USER_ID},
    timeout=600,
)
data = resp.json()

print("HTTP", resp.status_code)
print("code       :", data.get("code"))
print("request_id :", data.get("request_id"))
print("message    :", data.get("message"))
monitor = data.get("monitor") or {}
print("token      :", monitor.get("token_usage"), "| cache:", monitor.get("cache_hit"), "| cost:", monitor.get("cost_time"), "s")
d = data.get("data") or {}
print("file_name  :", d.get("file_name"))
print("text       :")
print(d.get("text"))
