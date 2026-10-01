"""请求 notes 域 checklist（复习清单）接口并解析返回字段。用法：python checklist.py

统一入口：POST /api/agent/v1，域与任务名在请求体（"domain": "notes", "task": "checklist"）。

checklist 必填：X-User-Id + extra.subject + docs——docs 里**必须包含一个 catalog json 文件名**
（上一步 catalog 响应里的 data.file_name），可再追加一个老师重点 .txt。
data.text 为精简摘要（统计 + 卡片列表，不含卡片正文）；完整 Markdown 落盘 result.md，页面版 checklist.html。
"""
import os
import uuid

import requests

BASE_URL = os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
URL = f"{BASE_URL}/api/agent/v1"
USER_ID = "1"
CATALOG = "20260907_201649_443.json"
DOCS = []
SUBJECT = "物理"

resp = requests.post(
    URL,
    json={
        "domain": "notes",
        "task": "checklist",
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
            "catalog": CATALOG,
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
