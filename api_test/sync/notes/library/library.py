"""请求 notes 域 library（资料入库）接口并解析返回字段。用法：python library.py

统一入口：POST /api/agent/v1，域与任务名在请求体（"domain": "notes", "task": "library"）。

library 必填：X-User-Id + extra.subject + docs（PPT/PDF/docx/xlsx/txt/图片全量入库）。
docs 里的文件名须已存在于**服务端** data/{USER_ID}/docs/ 下（本目录下的图片是样例，要先拷过去）。
入库后资料进入该用户该学科的知识库（向量索引），供检索与带出处问答。
无落盘产物：结果文本与统计只在 data.text 返回，data.file_name 为空串。
"""
import os
import uuid

import requests

BASE_URL = os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
URL = f"{BASE_URL}/api/agent/v1"
USER_ID = "1"
DOCS = ["U202314751_1.jpg", "U202314751_2.jpg", "U202314751_3.jpg", "U202314751_4.jpg", "U202314751_5.jpg", "U202314751_6.jpg", "U202314751_7.jpg", "U202314751_8.jpg", "U202314751_9.jpg", "U202314751_10.jpg",
        "U202314751_11.jpg","U202314751_12.jpg","U202314751_13.jpg","U202314751_14.jpg","U202314751_15.jpg","U202314751_16.jpg","U202314751_17.jpg","U202314751_18.jpg","U202314751_19.jpg","U202314751_20.jpg","U202314751_21.jpg"]
SUBJECT = "物理"

resp = requests.post(
    URL,
    json={
        "domain": "notes",
        "task": "library",
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
