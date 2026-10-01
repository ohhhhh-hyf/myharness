"""查询异步 minutes 任务状态。用法：python minutes_async_status.py

状态接口与另外三个接口返回同一份"任务快照"（8 字段），只是不含正文（text 恒为 null）。
status 给代码判断（queued/running/succeeded/failed），message 给人看进度或失败原因。
"""
import json
import os

import requests

BASE_URL = os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")   # 服务器用 8003 时：export AGENTFLOW_BASE_URL=http://127.0.0.1:8003

JOB_ID = os.getenv("JOB_ID") or "job_637547664132538372"   # 或 export JOB_ID=submit 返回的 job_id

if not JOB_ID:
    raise SystemExit("请先把 minutes_async_submit.py 返回的 job_id 填到 JOB_ID")

URL = f"{BASE_URL}/api/agent/v1/async/{JOB_ID}"

resp = requests.get(URL, timeout=60)

print("URL :", URL)
print("HTTP", resp.status_code)
try:
    data = resp.json()
except Exception:
    print(resp.text)
    raise

print(json.dumps(data, ensure_ascii=False, indent=2))

if data.get("code") != 0:                      # 调用失败：只有 code + message
    raise SystemExit(f"调用失败：{data.get('message')}")

monitor = data.get("monitor") or {}
print()
print("status     :", data.get("status"))
print("message    :", data.get("message"))
print("token      :", monitor.get("token_usage"), "| cache:", monitor.get("cache_hit"),
      "| cost:", monitor.get("cost_time"), "s")
