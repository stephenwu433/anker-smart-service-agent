# 比赛 MVP Backend Architecture

系统采用单体 FastAPI 服务和确定性编排器，匹配比赛期只有一名主技术负责人的交付约束。API route
负责 typed request/response 和 HTTP error；`ConversationOrchestrator` 负责状态机与风险优先路由；
`InMemoryKnowledgeBase` 提供可替换的审核知识检索；`MongoRepository` 保存会话、审计、服务事件、
人工动作和反馈。

## 当前请求链路

```text
HTTP request
    │
    ▼
FastAPI typed validation
    │
    ▼
ConversationOrchestrator
    ├── 附件能力检查 ───────────────► HANDOFF（未接文件 provider）
    ├── 当前消息安全规则 ───────────► BLOCK
    ├── 必要信息检查 ───────────────► ASK
    ├── IntentProvider + fallback
    └── KnowledgeProvider + answerability
            ├── 无法充电且有审核依据 ───► GUIDE
            ├── 其他有审核依据 ─────► RESOLVE（兼容状态）
            └── 无可靠依据 ─────────► HANDOFF
    │
    ▼
StorageRepository
    ├── MongoRepository（runtime）
    └── MemoryRepository（test）
```

每个会话内保存一个带 revision history 的 `CaseRecord`、多个 `AttemptRecord` 和一个可选
`TicketRecord`。Case 更正不会覆盖原始事实；Attempt 将建议、执行状态、观察和结果拆开；Ticket 将
人工回复、动作完成、用户确认解决和重开拆成带版本事件，从而避免把客服动作完成误报成用户问题已解决。

route 只负责 HTTP contract，状态判断、文案选择和审计数据生成位于 orchestrator；provider output
必须经过 Pydantic model 校验，不能直接控制持久化或执行客服动作。

当前实现使用 rule-based 理解和小型内置演示知识库，保证三条验收案例离线、可复现。它不是生产
模型效果声明，也不是真实商品知识。后续接入千问或其他 provider 时，应把结构化理解封装在独立
interface 后，强制使用 `EmpathyCard` 校验 model output，并为 timeout、空输出和非法 Schema 保留
确定性降级到 `HANDOFF`。真实 RAG 应替换知识库实现，但不得绕过知识 ID、版本和来源字段。

知识检索已封装为可注入的 `KnowledgeProvider`。当前 provider 会按意图过滤，并将不良反应、功效
承诺和交易问题判定为 demo 知识不可回答，避免“命中任意关键词就直接 RESOLVE”。生产 RAG 返回的
结果仍须执行 relevance、权限、时效和 answerability 校验，不能把向量相似度直接等同于可回答。

意图识别已经封装为可注入的 `IntentProvider`。外部 provider 只有在结构化结果校验通过且置信度
达到 `INTENT_MINIMUM_CONFIDENCE` 时才会被采用；timeout、异常、非法结果和低置信度统一降级到
`RuleBasedIntentProvider`。高风险症状和必要追问在 provider 调用前执行，确保外部模型故障时安全
规则仍有效。意图来源和置信度仅进入 Empathy Card 与客服审计视图，不暴露给消费者。

每轮安全与意图判断以当前消息为主，历史仅用于补充已确认的选购上下文，避免旧症状永久污染后续
问题。rule-based 安全 fallback 可识别常见否定、假设、第三方主体和已恢复表达；它只能降低明显
误报，不能替代 LLM/NLU 的语义判断。附件在文件 provider 接入前会明确说明无法读取并进入人工
确认流程，不会根据 filename 或 metadata 猜测内容。

MongoDB 使用 `conversations`、`audit_events`、`service_events`、`feedback` 和
`service_actions` collection。应用首次访问 persistence 时自动建立查询 indexes；其中
`conversation_id + idempotency_key` 使用 unique compound index，防止同一会话重复建单。连接具有
明确 timeout，URI 中的 credential 不写入代码或日志。

生产 deployment 仍需配置认证、TLS、备份和最小权限账号，并在 API 前增加身份认证、角色授权、
rate limit 和正式审计主体。当前审计主体标记为 `unauthenticated_agent_api`，用于明确暴露鉴权尚未
接入，而不是伪装成真实客服身份；配置化响应时间也不得作为未经运营确认的真实客服承诺。

## Production 接入路线

建议按依赖关系推进，而不是先绑定尚未确定的 vendor：

1. 扩展结构化理解结果，加入 entities、missing slots、multi-intent 和 answerability，并用真实语料
   建立 regression evaluation。
2. 实现 LLM `IntentProvider` 与 RAG `KnowledgeProvider`，保留现有 rule fallback、Schema 校验、
   timeout 和安全守卫。
3. 确定文件存储后，实现 `FileProvider`，再接图片识别与语音转文字；在此之前附件继续显式转人工。
4. 确定订单/售后服务后，通过 integration adapter 接入，不把 vendor-specific payload 泄漏到
   conversation domain model。
5. 接入 JWT 或企业 SSO/OIDC，并据此实现 RBAC、真实 audit actor、事件认领和数据访问范围。
6. 增加分页、optimistic locking、claim lease、retry/outbox，再连接消息或客服 webhook。

订单/售后、文件存储、鉴权和通知服务尚未选型；因此当前没有写死 vendor endpoint、credential 或
第三方 SDK。
