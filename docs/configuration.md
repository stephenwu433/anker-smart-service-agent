# Configuration

应用通过 `pydantic-settings` 读取 environment variable。

## 加载方式

默认读取项目根目录的 `.env`。如果设置了 `APP_CONFIG_FILE`，则读取该文件作为默认配置；process
environment 中的同名变量始终拥有更高优先级。

```bash
APP_CONFIG_FILE=config/test.env python -m smart_service_agent.cli
```

`scripts/dev.sh` 默认选择 `config/development.env`，也可以传入其他文件：

```bash
scripts/dev.sh config/production.env
```

## 可用设置

| Key | 类型 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `APP_NAME` | string | `Anker Smart Service Agent` | API 显示名称 |
| `APP_ENV` | enum | `development` | 当前 environment |
| `LOG_LEVEL` | string | `INFO` | application log level |
| `APP_HOST` | string | `127.0.0.1` | bind address |
| `APP_PORT` | integer | `8000` | bind port |
| `APP_RELOAD` | boolean | `false` | 是否启用 hot reload |
| `DATA_DIR` | path | `data` | data root directory |
| `MONGODB_URI` | string | `mongodb://127.0.0.1:27017` | MongoDB connection URI；credential 只能由 `.env` 或 runtime 注入 |
| `MONGODB_DATABASE` | string | `smart_service_agent` | MongoDB database name |
| `MONGODB_TIMEOUT_MS` | integer | `3000` | MongoDB connect 和 server selection timeout |
| `SCHEMA_VERSION` | string | `1.1` | 共情卡和人工接管包 Schema 版本 |
| `RULE_VERSION` | string | `risk-rules-v2` | 状态机和风险规则版本 |
| `KNOWLEDGE_VERSION` | string | `demo-knowledge-v1` | 当前演示知识版本 |
| `HANDOFF_ETA_MINUTES` | integer | `30` | 演示人工响应时间；不代表正式 SLA |
| `INTENT_MINIMUM_CONFIDENCE` | float | `0.7` | 外部意图 provider 结果被采用的最低置信度 |

## 安全边界

`config/` 中只能放非敏感默认值。API key、credential 和 private endpoint 必须存放在不被 Git
追踪的 `.env` 中，或由 deployment platform 注入。production 不应启用 `APP_RELOAD`。
