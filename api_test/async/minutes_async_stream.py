"""查看异步 minutes 任务事件流。用法：python minutes_async_stream.py

每行一个 JSON 事件，字段与另外三个接口同源：恒定带 type / job_id / status / message，
其余按事件补充（chunk 带 text、done 与结果接口逐字一致）。
"""
import json
import os

import requests

BASE_URL = os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")   # 服务器用 8003 时：export AGENTFLOW_BASE_URL=http://127.0.0.1:8003

JOB_ID = os.getenv("JOB_ID") or "job_637547664132538372"   # 或 export JOB_ID=submit 返回的 job_id
CURSOR = 0

if not JOB_ID:
    raise SystemExit("请先把 minutes_async_submit.py 返回的 job_id 填到 JOB_ID")

URL = f"{BASE_URL}/api/agent/v1/async/{JOB_ID}/stream?cursor={CURSOR}"

print("URL :", URL)
with requests.get(URL, stream=True, timeout=3600) as resp:
    print("HTTP", resp.status_code)
    if resp.status_code != 200:
        print(resp.text)
        raise SystemExit(1)
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            print(raw)
            continue
        etype = event.get("type")
        status = event.get("status")
        message = event.get("message")
        if etype == "chunk":
            print(f"[chunk]   {status:<9} {message} {((event.get('text') or ''))[:120]!r}")
        elif etype == "done":
            monitor = event.get("monitor") or {}
            print(f"[done]    {status:<9} {message} token={monitor.get('token_usage')} "
                  f"cost={monitor.get('cost_time')}s file={event.get('file_name')}")
            print(f"          正文长度 {len(event.get('text') or '')}")
        else:
            print(f"[{etype:<8}] {status:<9} {message}")
