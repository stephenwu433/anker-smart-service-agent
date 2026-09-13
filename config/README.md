# Config

此目录保存各 environment 的非敏感默认配置。

- `development.env`：本地开发和 hot reload。
- `test.env`：automated test 使用的隔离配置。
- `production.env`：production 的安全默认值，不包含 secret。

优先级从高到低为 process environment、`.env`、代码默认值。运行 `scripts/dev.sh` 时，选定的
config 文件会先加载到 process environment，因此会覆盖 `.env` 中的同名值。

API key、credential 和 private endpoint 等 secret 只能写入本地 `.env` 或由 deployment
platform 注入，禁止加入本目录或 commit 到 Git。
