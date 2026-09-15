# 比赛 MVP API

当前 backend 实现消费者咨询、人工接管和品牌洞察的同一条服务闭环。所有示例知识、事件处理人和
经营数据均属于 `demo`，不得解释为真实品牌业务数据或正式 SLA。

## 消费者端

### 发起和继续咨询

`POST /v1/conversations` 创建会话，`POST /v1/conversations/{conversation_id}/messages`
在同一会话补充信息。request 的主要字段如下：

```json
{
  "message": "第一次使用移动电源，应该怎么用？",
  "product": "演示移动电源",
  "order_reference": "DEMO-ORDER-001",
  "attachments": []
}
```

response 只包含消费者可见的自然语言、状态、依据与可执行动作，不暴露情绪标签、内部风险规则、
模型名称或推理过程。充电设备无法充电场景的 `GUIDE` 和兼容既有咨询的 `RESOLVE` 返回审核知识依据；
`ASK` 每轮只问一个关键问题；无审核依据时显式
进入 `HANDOFF`；命中设备安全风险时进入 `BLOCK`，停止排障并提示断电、停止使用和人工跟进。

每轮风险与意图判断以当前 `message` 为主，但已激活的 `safety_hold` 会持续生效：未明确解除的
设备风险不能被下一句换话题、继续使用或附件转人工覆盖。否定、假设、第三方主体和已恢复表达
仍不会误判为新的本机风险。订单、退款、退换货等复合表达在风险未解除时也不能重新进入排查。

附件字段当前只校验 `product_image` 或 `order_screenshot` metadata，属于后续文件 provider 的预留入口。
风险检查先于附件处理：消息本身命中设备风险时进入 `BLOCK`，并明确说明附件无法读取；没有风险时
才因无法读取内容而进入 `HANDOFF`。系统不执行真实图片识别，也不保存文件内容。

### Case 和 Attempt

- `GET /v1/conversations/{conversation_id}/case`：读取消费者原话、当前事实版本和全部修订历史。
- `POST /v1/conversations/{conversation_id}/case/revisions`：追加更正版本，不覆盖历史版本；随后
  按事实依赖撤回尚未执行的步骤，并重新检查风险和下一步。
- `GET /v1/conversations/{conversation_id}/attempts`：读取建议及执行历史，含 `withdrawn`。
- `POST /v1/conversations/{conversation_id}/attempts`：只接受知识目录中的 `action_id`；`GUIDE`
  时后端会自动创建当前步骤，重复的待执行步骤返回 `409`。
- `PATCH /v1/conversations/{conversation_id}/attempts/{attempt_id}`：记录执行或跳过、观察内容和
  结果。后端根据风险和结果决定继续、结束或升级，并返回 `attempt` 与下一轮 `response`。
  执行过的建议没有观察内容时返回 `422`；已撤回或 `based_on_revision` 落后于当前事实版本时返回
  `409`。

`GUIDE` 的 `ConsumerResponse.current_attempt` 包含当前唯一待执行步骤。消费者不需要先手工创建
Attempt，也不能提交自由填写的 recommendation。

### 人工交接和反馈

- `POST /v1/conversations/{conversation_id}/handoff`：记录用户是否同意转人工。同一未结束工单会
  复用原服务事件，不同 `idempotency_key` 也不会重复建单。
- `GET /v1/events/{event_id}`：查看等待接管、处理中或已完成状态及演示预计响应时间。
- `POST /v1/conversations/{conversation_id}/feedback`：把是否解决和开放反馈绑定到最新
  `result_id`。反馈只进入待分析数据，不自动训练模型或修改风险规则；若评论命中设备风险，会话仍会
  进入 `BLOCK`。
- `POST /v1/conversations/{conversation_id}/resolution`：由消费者确认问题已解决，这是把工单标为
  `resolved` 的唯一入口。

## 人工客服工作台

- `GET /v1/agent/events`：按风险优先级和等待时间返回事件队列。
- `GET /v1/agent/conversations/{conversation_id}`：返回消费者原话、共情卡、事实与推断、缺失
  信息、风险、知识依据、排查 Attempt、Case 更正、建议下一步和审计轨迹。`executed_actions` 仍只
  表示客服动作，与消费者排查记录分开。
- `POST /v1/agent/events/{event_id}/actions`：记录回复、索要材料、建立售后记录、升级专家或关闭
  事件。鉴权接入前审计主体明确记录为 `unauthenticated_agent_api`；生产环境必须用认证身份替换。
- `POST /v1/agent/conversations/{conversation_id}/ticket/results`：只接受人工回复、动作完成或重开。
  `user_confirmed_resolved` 必须由消费者确认接口写入；客服代填返回 `409`。

`GET /workspace/consumer` 和 `GET /workspace/agent` 提供无额外 frontend dependency 的最小可运行
工作区，用于联调消费者输入和人工队列。它们不包含 production 登录能力。

## 品牌洞察

`GET /v1/insights/overview` 返回咨询量、反馈解决率、转人工率、重复提问率和高频未解决问题。
每项指标包含时间范围、样本数和 `demo`/`real` 属性；默认且当前实际支持的属性为 `demo`。

## 状态和版本

全局状态为 `GUIDE`、`RESOLVE`、`ASK`、`HANDOFF` 和 `BLOCK`。MongoDB 持久化保存状态切换原因、规则版本、
知识版本、结果编号、人工动作和反馈。当前版本由 `SCHEMA_VERSION`、`RULE_VERSION` 和
`KNOWLEDGE_VERSION` 配置。

## 错误行为

- 空白或超过限制的输入返回 `422`。
- 不存在的会话或事件返回 `404`。
- feedback 的 `result_id` 不是该会话最新结果时返回 `409`。
- 已撤回或基于过期事实版本的 Attempt 更新返回 `409`。
- 客服接口写入 `user_confirmed_resolved` 返回 `409`。
- MongoDB 暂时不可用时返回不包含连接信息的 `503`。
- 无知识命中不会生成产品事实，而是显式请求转人工。

## 尚未实现

- 附件二进制上传、图片识别、语音转文字和真实文件存储。
- 订单/售后系统、企业登录或 SSO、消息通知和客服 webhook。
- 客服队列分页、事件认领、RBAC、optimistic locking 和多人并发冲突处理。

这些能力尚未选定 vendor。当前 API 只保留业务边界，不宣称 external service 已接入。
