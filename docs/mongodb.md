# MongoDB 本地开发与数据结构

比赛 MVP 使用 MongoDB 保存会话、审计、人工事件、feedback 和客服动作。MongoDB database 会在
第一次写入时自动建立，不需要提交初始化数据文件。

## 本地启动

本机安装 `mongod` 后，在一个 terminal 运行：

```bash
scripts/mongo-dev.sh
```

脚本只监听 `127.0.0.1:27017`，数据写入被 Git 忽略的 `data/mongodb/`。随后在另一个 terminal
运行 `scripts/dev.sh`。如需使用 Atlas 或其他 deployment，在本地 `.env` 或 runtime environment
设置 `MONGODB_URI`，不要把包含用户名或密码的 URI 写入 repository。

## Collection

| Collection | 内容 | 主要 index |
| --- | --- | --- |
| `conversations` | 当前会话、消息、共情卡和状态 | unique `conversation_id` |
| `audit_events` | 状态切换、转人工、feedback 和客服动作轨迹 | `conversation_id + created_at` |
| `service_events` | 人工接管事件、优先级和进度 | unique `event_id`；unique `conversation_id + idempotency_key`；`priority + created_at` |
| `feedback` | 与 `conversation_id`、`result_id` 绑定的解决反馈 | `conversation_id` |
| `service_actions` | 人工执行动作、参数和结果 | `event_id + created_at` |

应用在首次 persistence 操作时幂等创建 indexes。MongoDB 不可用时业务 endpoint 返回 `503` 和安全的
通用错误，不暴露 URI、credential 或 server detail；`/health` 不依赖 MongoDB，仍用于进程级探活。

## Production 要求

Production 应启用认证和 TLS，使用最小权限账号，并配置备份、监控与恢复演练。`MONGODB_URI` 只能
通过 secret manager 或 runtime environment 注入。`MONGODB_TIMEOUT_MS` 应结合 deployment 网络
延迟设置，但必须保留有限 timeout。
