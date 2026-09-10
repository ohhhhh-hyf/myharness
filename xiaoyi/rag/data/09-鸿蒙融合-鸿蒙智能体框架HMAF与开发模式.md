---
title: 鸿蒙智能体框架 HMAF 与开发模式
category: 鸿蒙融合
tags: [小艺, HMAF, 鸿蒙智能体框架, AgentFrameworkKit, A2A, 开发者]
updated: 2026-09-10
sources:
  - https://developer.huawei.com/consumer/cn/doc/doccenter-celia/skill-agent-0000002592931544
  - https://developer.huawei.com/consumer/cn/doc/service/platform-concepts-0000002625401382
  - HDC 2025 / HDC 2026 公开资料
---

# 鸿蒙智能体框架 HMAF 与开发模式

> 鸿蒙智能体框架（HMAF, Harmony Agent Framework）是华为为鸿蒙生态提供的智能体技术体系，
> 覆盖意图识别、任务调度、Agent 管理与 A2A 通信，并提供面向开发者的两套接入路线。

## 一、HMAF 是什么

- **定位**：鸿蒙系统面向 Agent 时代的基础设施，小艺作为系统级智能体承担核心调度角色；
- **发布**：2025 年 6 月 HDC 2025 发布，随小艺智能体开放平台一同推出；
- **演进**：HarmonyOS 6 / 鸿蒙 7（API 26）持续升级至 **HMAF 2.0**，提出"**意图即服务**"范式；
- **能力规模**（HMAF 2.0 支持）：可调用 2100+ 项系统能力、2000+ 个鸿蒙智能体、500+ 个伙伴精选 Skill，复杂任务成功率超 90%。

## 二、三层技术架构

| 层级 | 名称 | 职责 |
| --- | --- | --- |
| 系统层 | **HMAF 鸿蒙智能体框架** | 意图识别、任务调度、Agent 管理、A2A 通信；开发者无需感知底层 |
| 开发套件层 | **Agent Framework Kit** | 开发者接触最多：提供 `FunctionComponent`（对话 UI 组件）与 `AgentController`（会话控制器） |
| 生态层 | **A2A 接入协议 / 小艺开放平台** | 注册智能体、生成 agentId、配置技能、上架分发，支持系统全局语音唤起 |

## 三、两条主要开发路线

### 路线一：轻量化接入（`@kit.AgentFrameworkKit`）

- **零 AI 开发**：约 10 行 UI 代码即可嵌入已上架智能体；
- 内置能力：对话 UI、流式输出、上下文托管、跨设备同步；
- 适用场景：商城客服、健康问答、知识库助手等。

```text
应用 UI  →  FunctionComponent（对话界面）
         →  AgentController（会话控制：发起、监听、中断）
         →  平台侧智能体（agentId 绑定）
```

### 路线二：自建本地智能体（`AgentExtensionAbility`）

- 基于 `@kit.AbilityKit`，几行代码实现**本地技能智能体**；
- 支持 **A2A 跨应用调用**、系统小艺语音唤醒、**离线运行**；
- 适用场景：本地工具、跨应用协同、隐私敏感场景。

## 四、开发注意事项与常见坑

1. **平台前置**：需前往小艺开放平台创建智能体并获取 `agentId`，并将**应用包名与智能体 ID 绑定**；
2. **真机限制**：目前仅支持手机和平板真机（不支持模拟器），需登录华为账号并联网，**仅限中国大陆境内**；
3. **常见错误**：
   - `agentId` 无效：智能体未审核上架，或包名与平台配置不一致；
   - 无法唤起：`module.json5` 未配置 `exported: true`；
4. **合规要求**：智能体上架需通过平台审核，能力与内容需符合规范。

## 五、A2A 与多智能体协同

- **A2A（Agent to Agent）模式**：支持直连第三方智能体，实现多智能体跨域协同；
- **协议升级**：HMAF 2.0 升级 A2A、A2UI 协议；
- **生成式 A2UI**：由智能体动态生成适配的交互界面；
- **统一接口**：第三方智能体通过鸿蒙 Agent 通信协议、意图框架、AgentKit 与系统协同。

## 六、面向开发者的整体链路

```text
开发：LLM / 工作流 / A2A / VibeCoding（自然语言极简开发）
调试：真机调试 + 平台沙箱
上架：小艺开放平台审核 → 智能体广场分发
变现：华为 IAP 收银台（付费技能、订阅、内购）
激励：天工计划（现金激励 + 资源支持）
```

## 七、常见问题

| 问题 | 解答 |
| --- | --- |
| 不会 AI 能开发智能体吗？ | 可以：轻量化接入只需嵌入已上架智能体，写 UI 即可 |
| 智能体能离线运行吗？ | 本地智能体（AgentExtensionAbility）支持离线 |
| 支持哪些开发模式？ | LLM 模式、工作流模式、A2A 模式；平台另提供 VibeCoding 极简开发 |
| 能跨设备使用吗？ | 上架后可在手机、平板、智慧屏、车机等全鸿蒙终端触达 |

## 参考来源

- [华为官方文档：Skill 和智能体开发平台](https://developer.huawei.com/consumer/cn/doc/doccenter-celia/skill-agent-0000002592931544)
- [华为官方文档：小艺开放平台——平台概览与核心概念](https://developer.huawei.com/consumer/cn/doc/service/platform-concepts-0000002625401382)
- HDC 2025 / HDC 2026 公开资料
