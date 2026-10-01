"""批量跑 minutes 接口：读 now.xlsx 的会议文本 + 模板名，纪要写回第三列。

表格约定（默认读第一个 sheet）：

| 行 | A | B | C | D | E |
|---|---|---|---|---|---|
| 1 | `文本` | `场景` | `纪要` | `消耗时间` | `文本长度` |
| 2–56 | 会议文本 | 模板中文名（或 md 英文名） | 生成的纪要 | 接口耗时（秒，数值） | `原文/纪要` 字数 |

C/D/E 三列表头由脚本补写；D、E 的值在**本次运行生成本行纪要时**写入。

用法（在任意目录都可以；脚本自己定位仓库根）::

    python api_test/sync/meeting/minutes/minutes_from_excel.py --dry-run     # 只校验表格与模板名，不发请求
    python api_test/sync/meeting/minutes/minutes_from_excel.py --limit 1     # 先跑 1 行试水
    python api_test/sync/meeting/minutes/minutes_from_excel.py               # 跑第 2–56 行全部待处理

行为约定：

- **断点续跑**：C 列已有纪要的行直接跳过；`[失败]` / `[跳过]` 开头的行会重跑。
- **逐行保存**：每写完一行立即保存工作簿，长任务中断不丢结果。
- **就地写入先备份**：`--out` 等于输入文件时，第一次写入前复制一份 `test_sample.bak.xlsx`。
- 模板名先本地校验（用服务端同一套解析 `app.config.template_key`），
  名字不对的行直接标 `[跳过]` 并给出最接近的合法名，不浪费 token。
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import requests
from openpyxl import load_workbook

FAIL_PREFIX = "[失败]"
SKIP_PREFIX = "[跳过]"
DEFAULT_SHEET = ""  # 空 = 第一个 sheet


def repo_root() -> Path:
    """向上找含模板目录 template 的目录作为仓库根。"""
    for parent in Path(__file__).resolve().parents:
        if (parent / "template").is_dir():
            return parent
    return Path.cwd()


ROOT = repo_root()


def make_template_resolver():
    """模板名 → 是否合法 + 最接近的合法名（与服务端同一套解析）。"""
    sys.path.insert(0, str(ROOT))
    try:
        from app.config import template_key, template_registry  # noqa: PLC0415

        names = sorted({str(item.get("name") or "") for item in template_registry().values() if item.get("name")})
        ids = sorted({str(item.get("template") or "") for item in template_registry().values() if item.get("template")})

        def resolve(value: str) -> bool:
            return bool(template_key(value))

    except Exception as exc:  # noqa: BLE001 - 导入失败时不拦，交给服务端 400
        print(f"⚠ 无法导入 app.config（{exc}）→ 跳过本地模板名校验", flush=True)
        names, ids = [], []

        def resolve(value: str) -> bool:
            return bool((value or "").strip())

    def suggest(value: str) -> str:
        pool = names + ids
        hit = difflib.get_close_matches((value or "").strip(), pool, n=1, cutoff=0.5)
        return hit[0] if hit else ""

    return resolve, suggest


def save_workbook(wb, out: Path) -> bool:
    """保存工作簿；被 Excel 占用时给出可执行提示而不是抛栈。"""
    try:
        wb.save(out)
        return True
    except PermissionError:
        print(f"✗ 无法写入 {out.name}：文件被其它程序占用（通常是 Excel 正打开着）。\n"
              f"  请先关闭该文件再重跑；或临时写到别处：--out {out.with_name(out.stem + '.new' + out.suffix).name}", flush=True)
        return False


def build_payload(transcript: str, template: str, date: str) -> dict:
    """与 api_test/sync/meeting/minutes/minutes.py 完全同构的请求体。"""
    return {
        "domain": "meeting",
        "task": "minutes",
        "time": date,
        "texts": {"transcript": transcript, "keypoints": "", "notes": ""},
        "docs": [],
        "memory": False,
        "extra": {
            "template": template,
            "profile": "",
            "project": "",
            "subject": "",
            "style": "",
            "memory": False,
        },
    }


def call_minutes(url: str, transcript: str, template: str, date: str, user: str, timeout: int) -> tuple[bool, str, str, int]:
    """调一次 minutes（同步）。返回 (成功?, 纪要或错误说明, 统计串, token 数)。"""
    try:
        resp = requests.post(
            url,
            json=build_payload(transcript, template, date),
            headers={"X-Request-Id": uuid.uuid4().hex, "X-User-Id": user},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, f"请求异常：{exc}", "", 0

    try:
        body = resp.json()
    except ValueError:
        return False, f"HTTP {resp.status_code} 非 JSON 响应：{resp.text[:200]}", "", 0

    monitor = body.get("monitor") or {}
    token_usage = monitor.get("token_usage")
    token_n = int(token_usage) if isinstance(token_usage, (int, float)) else 0
    stats = "token=%s cache=%s 用时=%ss" % (
        token_usage,
        monitor.get("cache_hit"),
        monitor.get("cost_time"),
    )
    data = body.get("data") or {}
    text = str(data.get("text") or "").strip()
    # 成功判定按接口约定：code=0 为成功，非 0 时该值等于 HTTP 状态码（notes_api.md 2.3）
    if resp.status_code == 200 and str(body.get("code")) == "0" and text:
        return True, text, stats, token_n
    return False, f"HTTP {resp.status_code} code={body.get('code')} message={body.get('message')}", stats, token_n


def main() -> int:
    ap = argparse.ArgumentParser(description="now.xlsx → minutes 接口 → 纪要写回 C 列")
    ap.add_argument("--file", default=str(ROOT / "now.xlsx"), help="输入工作簿（默认仓库根 now.xlsx）")
    ap.add_argument("--sheet", default=DEFAULT_SHEET, help="sheet 名（默认第一个）")
    ap.add_argument("--start", type=int, default=2, help="起始行（默认 2）")
    ap.add_argument("--end", type=int, default=56, help="结束行（默认 56，含）")
    ap.add_argument("--col-text", type=int, default=1, help="文本列（默认 1 = A）")
    ap.add_argument("--col-template", type=int, default=2, help="模板列（默认 2 = B）")
    ap.add_argument("--col-out", type=int, default=3, help="纪要列（默认 3 = C）")
    ap.add_argument("--col-elapsed", type=int, default=4, help="消耗时间列（默认 4 = D，秒）")
    ap.add_argument("--col-len", type=int, default=5, help="文本长度列（默认 5 = E，格式 原文/纪要）")
    ap.add_argument("--out", default="", help="输出工作簿（默认就地写入，先备份 .bak.xlsx）")
    ap.add_argument("--base-url", default=os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000"), help="服务地址（支持环境变量 AGENTFLOW_BASE_URL，默认 http://127.0.0.1:8000）")
    ap.add_argument("--path", default="/api/agent/v1", help="统一入口路径（domain/task 在请求体）")
    ap.add_argument("--user", default="test", help="X-User-Id（默认 test）")
    ap.add_argument("--date", default="", help="请求体 time 字段（默认空串；需要固定会议日期时再传）")
    ap.add_argument("--timeout", type=int, default=1800, help="单请求超时秒数（默认 1800）")
    ap.add_argument("--retries", type=int, default=1, help="网络异常重试次数（默认 1）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个待处理行（0 = 全部）")
    ap.add_argument("--force", action="store_true", help="已有纪要的行也重跑（用于补写消耗时间/文本长度）")
    ap.add_argument("--rows", default="", help="只跑指定行（逗号分隔，如 4,9,15；隐含 --force，用于重跑个别行）")
    ap.add_argument("--dry-run", action="store_true", help="只校验表格/模板名/请求体，不发请求、不写文件")
    ap.add_argument("--progress-file", default="", help="把进度写成 JSON（服务器上可 cat/监控；不填则不写）")
    args = ap.parse_args()

    date = args.date  # 默认空串：请求体 time 留空即可
    src = Path(args.file).resolve()
    out = Path(args.out).resolve() if args.out else src
    if not src.is_file():
        print(f"✗ 找不到输入文件：{src}", flush=True)
        return 2

    wb = load_workbook(src)
    ws = wb[args.sheet] if args.sheet else wb[wb.sheetnames[0]]
    print(f"工作簿：{src.name}（sheet={ws.title}，共 {ws.max_row} 行 × {ws.max_column} 列）", flush=True)
    print(f"接口：{args.base_url}{args.path}｜X-User-Id={args.user}｜time={date}｜行 {args.start}–{args.end}", flush=True)

    resolve, suggest = make_template_resolver()

    # ① 预检：收集待处理行，剔除已完成的
    only_rows = {int(x) for x in args.rows.replace("，", ",").split(",") if x.strip()} if args.rows.strip() else None
    if only_rows:
        print(f"仅处理指定行：{sorted(only_rows)}（隐含 --force）", flush=True)
    pending: list[tuple[int, str, str]] = []
    skipped_invalid: list[tuple[int, str, str]] = []
    skipped_done = 0
    for row in range(args.start, args.end + 1):
        if only_rows is not None and row not in only_rows:
            continue
        transcript = str(ws.cell(row=row, column=args.col_text).value or "").strip()
        template = str(ws.cell(row=row, column=args.col_template).value or "").strip()
        current = str(ws.cell(row=row, column=args.col_out).value or "").strip()
        if not transcript and not template:
            continue
        if not transcript:
            skipped_invalid.append((row, template, "文本列为空"))
            continue
        if current and not current.startswith((FAIL_PREFIX, SKIP_PREFIX)) and not args.force and only_rows is None:
            skipped_done += 1
            # 历史行：文本长度可从表里算出，补上；消耗时间当时没记录，留空
            ws.cell(row=row, column=args.col_len, value=f"{len(transcript)}/{len(current)}")
            continue
        if not resolve(template):
            tip = suggest(template)
            skipped_invalid.append((row, template, f"模板名无效（最近：{tip or '—'}）"))
            continue
        pending.append((row, transcript, template))

    for row, template, why in skipped_invalid:
        print(f"  {SKIP_PREFIX} 行{row} 模板={template!r}：{why}", flush=True)
    print(f"预检：待处理 {len(pending)} 行｜已完成跳过 {skipped_done} 行｜无效跳过 {len(skipped_invalid)} 行", flush=True)

    if args.dry_run:
        for row, transcript, template in pending[: max(3, min(len(pending), 5))]:
            body = build_payload(transcript, template, date)
            print(f"  dry-run 行{row}：文本 {len(transcript)} 字｜模板 {template}｜"
                  f"extra={body['extra']}｜time={body['time']}", flush=True)
        print("dry-run 结束：未发请求、未写文件。", flush=True)
        return 0

    if not pending:
        print("没有待处理行。", flush=True)
        return 0
    if args.limit:
        pending = pending[: args.limit]

    # ② 写表头 + 备份
    for col, title in (
        (args.col_out, "纪要"),
        (args.col_elapsed, "消耗时间"),
        (args.col_len, "文本长度"),
    ):
        if str(ws.cell(row=1, column=col).value or "").strip() != title:
            ws.cell(row=1, column=col, value=title)
    if out == src:
        backup = src.with_suffix(".bak.xlsx")
        if not backup.is_file():
            shutil.copy2(src, backup)
            print(f"已备份原表：{backup.name}", flush=True)
    save_workbook(wb, out)

    url = f"{args.base_url}{args.path}"
    ok = fail = 0
    token_total = 0
    started = time.time()
    for i, (row, transcript, template) in enumerate(pending, start=1):
        print(f"[{i}/{len(pending)}] 行{row} 模板={template} 文本={len(transcript)}字 … ", end="", flush=True)
        t0 = time.time()
        success, text, stats, tokens = False, "", "", 0
        for attempt in range(args.retries + 1):
            success, text, stats, tokens = call_minutes(url, transcript, template, date, args.user, args.timeout)
            if success or not text.startswith("请求异常"):
                break
            print(f"重试{attempt + 1}… ", end="", flush=True)
            time.sleep(3)

        cost = time.time() - t0
        if success:
            ws.cell(row=row, column=args.col_out, value=text)
            # 消耗时间：数值（显示成「23.4秒」，便于统计平均/中位数）
            el = ws.cell(row=row, column=args.col_elapsed, value=round(cost, 1))
            el.number_format = '0.0"秒"'
            # 文本长度：原文/纪要 字数
            ws.cell(row=row, column=args.col_len, value=f"{len(transcript)}/{len(text)}")
            ok += 1
            print(f"✓ 纪要 {len(text)} 字（{cost:.0f}s，{stats}）", flush=True)
        else:
            ws.cell(row=row, column=args.col_out, value=f"{FAIL_PREFIX}{text}")
            fail += 1
            print(f"✗ {text}（{cost:.0f}s）", flush=True)
        for row_err, template_err, why in skipped_invalid:
            ws.cell(row=row_err, column=args.col_out, value=f"{SKIP_PREFIX}{why}：{template_err}")
        save_workbook(wb, out)  # 逐行保存：中断不丢已完成的结果

        # 进度汇总（每行一行，便于服务器上 tail -f 看进度与 ETA）
        token_total += tokens
        done_n = ok + fail
        elapsed = time.time() - started
        avg = elapsed / done_n if done_n else 0.0
        remain_n = len(pending) - done_n
        print(
            "    进度 %d/%d｜成功 %d 失败 %d｜均 %.1fs｜已用 %.1f 分钟｜预计剩余 %.1f 分钟｜累计 token %.2fM"
            % (done_n, len(pending), ok, fail, avg, elapsed / 60, avg * remain_n / 60, token_total / 1e6),
            flush=True,
        )
        if args.progress_file:
            Path(args.progress_file).write_text(
                json.dumps(
                    {
                        "total": len(pending), "done": done_n, "ok": ok, "fail": fail,
                        "current_row": row, "elapsed_minutes": round(elapsed / 60, 2),
                        "eta_minutes": round(avg * remain_n / 60, 2),
                        "token_total": token_total, "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    total = time.time() - started
    print(f"\n完成：成功 {ok}｜失败 {fail}｜无效跳过 {len(skipped_invalid)}｜已完成跳过 {skipped_done}"
          f"｜总用时 {total / 60:.1f} 分钟", flush=True)
    print(f"结果已写入：{out}", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
