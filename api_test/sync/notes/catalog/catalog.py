"""请求 notes 域 catalog（知识目录）接口并解析返回字段。用法：python catalog.py

统一入口：POST /api/agent/v1，域与任务名在请求体（"domain": "notes", "task": "catalog"）。

catalog 必填：X-User-Id + extra.subject（学科，中文自动转拼音）。
docs 里的 .txt 作为「老师重点」读取，其余按资料处理；无输入文本时按该学科已入库资料生成/增量更新。
产物：目录数据 json 写在 data/{user_id}/knowledge/catalogs/{学科拼音}/（data.file_name 为文件名），
data.text 为目录树 Markdown，同时落盘 result.md；下一行 checklist 的 docs 填的就是这个 json 文件名。
"""
import os
import uuid

import requests

BASE_URL = os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
URL = f"{BASE_URL}/api/agent/v1"
USER_ID = "1"
DOCS = []
SUBJECT = "物理"

resp = requests.post(
    URL,
    json={
        "domain": "notes",
        "task": "catalog",
        "time": "",
        "texts": {
            "transcript": "",
            "keypoints": "",
            "notes": "",
        },
        "docs": DOCS,
        "memory": False,
        "extra": {
            "template": "",
            "profile": "",
            "project": "",
            "subject": SUBJECT,
            "style": "",
            "memory": False,
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
