"""下载 checklist 产物：GET /api/agent/v1/file/{request_id}/{file_name}。

统一入口：域与任务名不再出现在路径里，下载只认 request_id + file_name
（产物目录 data/{user_id}/output/{request_id}/ 由 request_id 唯一确定）：
- request_id：POST /api/agent/v1（"domain":"notes","task":"checklist"）响应里的 request_id
- file_name ：该响应里的 data.file_name（checklist 有页面版 → checklist.html）
- user_id   ：URL 参数 ?user_id= 或 X-User-Id 头，二者取一

响应带 Content-Disposition: attachment（强制下载），文件存到本目录 downloads/ 下。
同一产物目录里还有 result.md（完整 Markdown；响应 data.text 只是精简摘要，不含卡片正文）。
想在浏览器里直接看页面版（不落盘），用预览端点（唯一保留域/线名的形态）：
    GET /api/v1/notes/checklist/preview?request_id=…&user_id=…

用法：python checklist_get.py
"""
import os
from pathlib import Path

import requests

BASE_URL = os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USER_ID = "1"

# ── 请求参数 ──
REQUEST_ID = ""                     # ← 自己填：POST 响应里的 request_id
FILE_NAME = "checklist.html"        # ← 响应里的 data.file_name；完整 Markdown 用 result.md

if not REQUEST_ID:
    print("请先把 REQUEST_ID 填成 POST checklist 响应里的 request_id")
    raise SystemExit(1)

URL = f"{BASE_URL}/api/agent/v1/file/{REQUEST_ID}/{FILE_NAME}?user_id={USER_ID}"

resp = requests.get(URL, timeout=60)

print("URL       :", URL)
print("HTTP", resp.status_code, "|", resp.headers.get("content-type"))
print("attachment:", resp.headers.get("content-disposition", "无（该端点应为 attachment）"))
if resp.status_code == 200:
    out = Path(__file__).resolve().parent / "downloads" / Path(FILE_NAME).name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(resp.content)
    print("已保存    :", out, f"（{len(resp.content)} bytes）")
else:
    print("失败      :", resp.text[:300])
