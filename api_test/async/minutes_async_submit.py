"""提交异步 minutes 任务。用法：python minutes_async_submit.py"""
import json
import os

import requests

BASE_URL = os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")   # 服务器用 8003 时：export AGENTFLOW_BASE_URL=http://127.0.0.1:8003

# ── 会议转写文本（三引号内直接粘贴）──
TRANSCRIPT = """
周宁：今天主要复盘「小艺慧记Agent开发进展」第一阶段情况，确认8月下旬内测前必须收口的事项。当前整体进度大约完成60%，会议纪要、待办提取、风险分析、思维导图这几条主线已经能跑通，Gradio测试界面也可以支持上传会议文本、选择任务并预览结果。但从最近几轮测试看，用户最关心的不是“能不能生成”，而是生成内容是否稳定、结构是否清楚、能不能解释为什么这么写。

林夏：算法侧目前最大进展是会议理解和纪要生成的主流程稳定了，基础事实抽取比上周好很多。现在的问题集中在两个地方：第一，会议模板匹配还不够准，一些销售复盘会会被识别成普通项目周会；第二，用户笔记和关键点的溯源还不够充分，模型有时只挂上十几条证据，导致用户觉得自己写的重点没有被认真利用。我们已经新增了 minutes_trace 任务，目标是在纪要基础上把用户笔记和关键点尽量挂到对应段落，但还需要优化对齐策略。

赵衡：后端这边已经把任务目录做了整理，meeting 和 notes 的公共运行逻辑都归到了 tools 层。现在 memory 只在 meeting 的 minutes、minutes_styles，以及 notes 的 graph 上启用。会议记忆的写回已经能记录项目目的、议题、决策、风险、未决项和场次快照。第一次会议如果用户不传 project，会自动生成 p1；如果传了“小艺慧记Agent开发进展”，就会按这个项目写入。后续会议会先用 project_key 和显式项目名匹配，再用实体重叠做弱匹配。

钱屿：前端界面上，本周主要修了上传控件高度不够、字体被挡住的问题，也把 minutes_trace 的自定义模板入口去掉了。因为现在已经有前置场景匹配和通用兜底模板，用户再填模板反而容易混淆。现在溯源材料区只保留用户关键点和用户笔记。下一步我建议把记忆引用展示做得更自然，不要出现“记忆1、记忆2”这种工程化标记，而是对用到历史记忆的内容加下划线，点击后展开来源。

陈澄：测试侧发现三类问题需要在内测前解决。第一，minutes_trace 在复杂会议中仍可能把会议结论写散，尤其是风险、阻塞和行动项之间边界不够清晰；第二，记忆引用虽然能出现，但用户还看不出来自哪一次会议；第三，部分输出中仍有“记忆命中显示”这类系统表达，放在用户报告里不够自然。建议把记忆来源展示放到底部，显示历史会议名称、时间、类型和原片段。

沈越：交付视角看，内测用户会用真实会议资料来试，不会理解我们内部的 task 名称。对他们来说，最重要的是三件事：结构稳定、证据可信、历史进展能接上。比如今天这场会如果写入记忆，下一场再讲“小艺慧记Agent开发进展”，系统应该知道之前已经完成了任务目录整理、Gradio基础界面、minutes_trace 初版和会议记忆写回，而不是每次都当成新项目。

周宁总结：本次会议形成四项结论。第一，8月18日前林夏继续优化 minutes_trace 的场景匹配、模板输出要求和证据对齐策略，目标是用户关键点和笔记在不捏造事实的前提下尽可能挂上。第二，赵衡在8月19日前补齐记忆引用的来源字段，包括历史会议时间、会议名称、类型和关联对象。第三，钱屿在8月20日前把 Gradio 界面中 minutes_trace 的模板入口彻底移除，并保留关键点、笔记上传入口。第四，陈澄在8月21日前准备一组前后两场会议的记忆测试样例，重点验证第二场是否能接住第一场的项目进展。

风险方面，当前最大风险是记忆能力已经可用，但可解释性还不够像用户产品。如果用户看不到“用了哪次历史会议”，会误以为系统在凭空补充。另一个风险是 minutes_trace 的证据挂载如果太少，会削弱用户对溯源纪要的信任。未决事项是：是否在内测版默认开启记忆引用下划线展示，还是先作为实验开关提供。
"""

URL = f"{BASE_URL}/api/agent/v1/async"
USER_ID = "1"

resp = requests.post(
    URL,
    json={
        "domain": "meeting",
        "task": "minutes",
        "time": "2026-09-01",
        "texts": {
            "transcript": TRANSCRIPT,
            "keypoints": "",
            "notes": "",
        },
        "docs": [],
        "memory": True,
        "extra": {
            "template": "",
            "profile": "",
            "project": "",
            "subject": "",
            "style": "",
            "memory": True,
        },
    },
    headers={"X-User-Id": USER_ID},
    timeout=60,
)

print("HTTP", resp.status_code)
try:
    data = resp.json()
except Exception:
    print(resp.text)
    raise

print(json.dumps(data, ensure_ascii=False, indent=2))

# ── 统一响应体：四个异步接口都返回这 8 个字段（见 API.md 第 3 节）──
print()
print("code       :", data.get("code"))          # 0=调用成功；非 0=HTTP 状态码
print("job_id     :", data.get("job_id"))        # 填到下三个脚本的 JOB_ID
print("request_id :", data.get("request_id"))
print("status     :", data.get("status"))        # 提交后必然 queued
print("message    :", data.get("message"))       # 阶段名或失败原因
print("text       :", data.get("text"))          # 提交时还没有产物
print("file_name  :", data.get("file_name"))
print("monitor    :", data.get("monitor"))
