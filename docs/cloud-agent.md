# Cloud Agent 开发环境

本仓库通过 `.cursor/environment.json` 定义 Cursor Cloud Agent 的开发环境。配置随代码版本化，
新启动的 agent 会按 branch 上的定义自动构建，无需在 dashboard 手动维护。

## 组成

- **Base image**：`.cursor/Dockerfile` 基于 `ubuntu:24.04`，安装 `git`、`curl`、Python 3.12
  toolchain（`python3`、`python3-venv`、`python3-pip`）以及从官方 apt repository 安装的
  MongoDB 8.0（`mongodb-org`，包含 `mongod` server 与 `mongosh` shell）。以内置非 root 用户
  `ubuntu` 运行。
- **install**：`bash scripts/bootstrap.sh`。checkout 后创建 `.venv`、安装 application 与 dev
  dependency，并在缺失时从 `.env.example` 生成 `.env`。脚本可重复执行（idempotent）。
- **start**：`bash .cursor/start.sh`。每次启动时拉起本地 MongoDB：已在运行则直接返回，否则清理
  上次非正常退出的 `mongod.lock`、以 `--fork` 后台启动 `mongod`（`dbpath=data/mongodb`，
  监听 `127.0.0.1:27017`，日志写入 `data/mongod.log`），并轮询 readiness 后返回。
- **terminals**：名为 `api` 的常驻终端运行 `bash scripts/dev.sh`，即 uvicorn dev server
  （`http://127.0.0.1:8000`），提供 `/health`、`/docs` 与 `/v1` API，日志可见、可重启。
- **ports**：暴露容器内 `8000` 端口。

## 生命周期约定

- 依赖安装与 source 派生的准备工作放在 `install`，构建 build 时执行一次并进入 snapshot；新 pod
  启动不会重跑 `install`。
- 每次启动都需要的 MongoDB 由 `start` 负责，脚本保证重复执行安全并显式检查 readiness。
- 需要可见日志与随时重启的 dev server 放在 `terminals`。

## 配置来源与优先级

committed 的 `.cursor/environment.json` 属于 repository-file managed 环境，优先级高于 dashboard
中的 personal / team 配置。修改环境即修改该文件并随 PR 合入；测试某个分支的环境改动时，可对该
分支触发 build 验证。

## 与本地开发的关系

Cloud Agent 环境复用仓库既有的 `scripts/` 与 `config/development.env`，命令与
[开发环境](development.md)、[MongoDB](mongodb.md) 文档保持一致，不引入独立的运行方式。
