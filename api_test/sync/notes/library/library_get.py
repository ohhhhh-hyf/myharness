"""【注意】library 没有可下载的产物，本脚本的请求预期返回 404，留着只为四条线形态一致。

library（资料入库）的结果**不落盘**：入库统计与正文只在响应 data.text 里返回，
data.file_name 是空串（源码里 library / graph 被明确排除在 md/html 落盘之外，
且 graph 的页面版由另一步单独导出）。产物目录 data/{user_id}/output/{request_id}/ 下
不会生成任何文件，所以下载端点必然 404 —— 这正是"这条线没有产物"的直接体现。
要查阅入库结果：看 POST 响应的 data.text（或 data/monitor 下的向量库统计）。

统一入口：POST /api/agent/v1（"domain":"notes","task":"library"）。
下载端点：GET /api/agent/v1/file/{request_id}/{file_name} —— 只认 request_id + file_name，
域与任务名不在路径里（产物目录由 request_id 唯一确定）。

用法：python library_get.py
"""
import os
from pathlib import Path

import requests

BASE_URL = os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USER_ID = "1"

# ── 请求参数 ──
REQUEST_ID = ""                  # ← 自己填：POST 响应里的 request_id
FILE_NAME = "result.md"          # ← 这条线没有产物，任何文件名都会 404（见上方说明）

if not REQUEST_ID:
    print("请先把 REQUEST_ID 填成 POST library 响应里的 request_id")
    raise SystemExit(1)

URL = f"{BASE_URL}/api/agent/v1/file/{REQUEST_ID}/{FILE_NAME}?user_id={USER_ID}"

print("提示：library 无落盘产物（响应 data.file_name 为空串），下面这次请求预期 404。")
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
