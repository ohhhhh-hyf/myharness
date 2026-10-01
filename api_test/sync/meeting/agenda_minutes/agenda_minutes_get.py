"""下载 agenda_minutes 产物：GET /api/agent/v1/file/{request_id}/{file_name}。

统一入口：域与任务名不再出现在路径里，下载只认 request_id + file_name
（产物目录 data/{user_id}/output/{request_id}/ 由 request_id 唯一确定）：
- request_id：POST /api/agent/v1（"domain":"meeting","task":"agenda_minutes"）响应里的 request_id
- file_name ：该响应里的 data.file_name（本脚本默认 agenda_minutes.html）
- user_id   ：URL 参数 ?user_id= 或 X-User-Id 头，二者取一

响应带 Content-Disposition: attachment（强制下载），文件存到本目录 downloads/ 下。
想在浏览器里直接看页面版（不落盘），用预览端点：
    GET /api/v1/meeting/agenda_minutes/preview?request_id=…&user_id=…
想取 Markdown 正文：把 FILE_NAME 换成 result.md（agenda_minutes 线的 md 产物名就是 result.md）。

用法：python agenda_minutes_get.py
"""
import os
from pathlib import Path

import requests

BASE_URL = os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USER_ID = "1"

# ── 请求参数 ──
REQUEST_ID = ""                  # ← 自己填：POST agenda_minutes 响应里的 request_id
FILE_NAME = "agenda_minutes.html"       # ← 响应里的 data.file_name；Markdown 用 result.md

if not REQUEST_ID:
    print("请先把 REQUEST_ID 填成 POST agenda_minutes 响应里的 request_id")
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
