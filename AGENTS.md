# 仓库开发规范

本文件适用于整个仓库。任何代码、配置、测试、文档和维护变更都必须遵守这些规范。

## 项目目标

- 构建可靠、可维护的 AI service intelligence API。
- 优先采用范围小、易于 review、行为清晰且有明确测试的变更。
- 保持服务能够在本地运行，并为后续 production deployment 做好准备。
- 没有明确需求时，不引入新的 framework、external service 或 architecture layer。

## 开始修改之前

1. 阅读 `README.md`、`CHANGELOG.md` 和 `docs/` 下的相关文件。
2. 编辑前检查现有实现和测试。
3. 保留用户无关的修改，避免大范围 mechanical rewrite。
4. 只有当决定会实质影响产品行为、数据、安全、兼容性或 external integration 时才请求确认；
   其他情况采用保守且合理的假设继续推进。

## 语言与沟通

- 解释、进度同步、文档叙述、commit 摘要和其他非专业沟通使用中文。
- 已有且通用的 technical terms 保持英文，以确保表达清晰准确，例如 API、endpoint、schema、
  prompt、model、token、fallback、mock、test、deployment、rollback、commit、branch 和 dependency。
- 不对标准 technical terms 进行生硬的中文直译。
- 代码 identifier、command、configuration key、filename、protocol name、error message 和第三方
  product name 保持原始语言。
- 首次使用不常见的 technical term 时，如果读者可能不了解，应附一句简洁的中文解释。
- 除非需求指定其他语言，否则 `README.md`、`docs/`、`CHANGELOG.md`、issue、review 内容和最终
  交付说明都遵循相同的语言规范。

## Architecture 与代码

- application code 放在 `src/smart_service_agent/` 下。
- test 放在 `tests/` 下，并在可行时对应 source structure。
- 各 environment 的非敏感默认值放在 `config/`；secret 只能由 `.env` 或 runtime environment
  提供。
- 本地数据按 `data/raw`、`data/interim`、`data/processed` 分层，实际数据文件不得 commit。
- prototype 和一次性实验放在 `sandbox/`；稳定逻辑必须迁入 `src/`，production code 不得
  import `sandbox/`。
- 可重复使用的开发 command 放在 `scripts/`，shell script 必须使用 strict mode、引用所有
  variable、校验 input，并保证重复执行安全。
- API route 保持精简；business logic 放入职责单一、interface 清晰的 module。
- public function 和不易理解的 internal function 必须使用 type hint。
- 优先使用明确的 data model 和 dependency injection，避免 global mutable state。
- environment-backed settings 集中放在 `config.py`；禁止 hard-code credential、token、private
  endpoint 或特定环境的 secret。
- 只有 standard library 和现有 dependency 无法满足需求时才新增 dependency，并在
  `pyproject.toml` 中设置合理的 version range。
- 除非需求明确要求 breaking change，否则保持已发布 API contract 的 backward compatibility。

## API 要求

- 使用 typed model 验证 request 和 response data。
- 返回一致、可操作的 error，且不得泄露 secret 或内部 stack trace。
- health endpoint 必须轻量，且不依赖 optional external service。
- 新增或修改 endpoint 时，同步说明 input、output、error case 和 configuration。
- breaking API change 必须在 `docs/` 中提供 migration guide，并在 `CHANGELOG.md` 中归入
  `Changed` 或 `Removed`。

## AI 与数据要求

- model/provider integration 必须封装在 interface 后，以便替换并在 test 中 mock。
- prompt、model name、timeout、retry limit 和 sampling setting 必须明确配置。
- 禁止记录 raw secret、credential 或敏感 user content。
- 将 model output 视为 untrusted input，在持久化或 tool use 前进行验证。
- parsing、routing、validation 和 fallback logic 必须有 deterministic unit test。
- 行为依赖 nondeterministic model 时，在 automated test 中 mock provider，并单独记录 evaluation
  method。

## Test 与验证

- 每项行为变更必须有 test，覆盖 happy path 和相关 failure path。
- 每个 bug fix 必须有 regression test，且该 test 在未修复时应失败。
- 完成开发前运行：

  ```bash
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/pytest
  ```

- 如果某项检查无法运行，必须明确说明跳过的检查及原因。
- 不得仅为让变更通过而削弱、删除或 skip test。

## 文档（`docs/`）

- 代码变更必须同步更新相关文档。
- `README.md` 只保留项目目的、quick start、核心 command 和相关链接。
- 详细的 architecture、API behavior、operation、integration、decision 和 migration guide 放在
  `docs/` 下。
- 以下变更必须创建或更新对应的 Markdown 文档：
  - 新的 user-visible workflow 或 API；
  - 新的 environment variable 或 external dependency；
  - architecture 或 operation decision；
  - deployment、migration、privacy 或 security consideration。
- 仓库文档之间使用 relative link，并验证链接有效。
- code example 必须与当前 public API 一致，并尽量保证可以直接运行。

## Changelog（`CHANGELOG.md`）

- 所有 user-visible、API、configuration、dependency、operation、security 或 compatibility 变更
  都必须更新 `CHANGELOG.md`。
- 新条目写在 `[Unreleased]` 下，并使用 Keep a Changelog category：`Added`、`Changed`、
  `Deprecated`、`Removed`、`Fixed` 或 `Security`。
- 从用户视角描述影响，不记录无关的 implementation detail。
- 纯格式调整或没有 observable impact 的 internal refactor 不写入 Changelog。
- release 时，把未发布条目移动到带日期的 semantic version section，并重新建立空的
  `[Unreleased]` section。

## Security 与隐私

- local secret 只能保存在 `.env`；`.env.example` 只能包含安全的 placeholder。
- 禁止 commit API key、access token、customer data、generated credential 或私有的 model
  input/output。
- 验证所有 external input，并为 network call 设置明确的 timeout。
- 尽量减少数据收集和保留。实现敏感 data flow 前，必须先在 `docs/` 中说明。

## 完成标准

一项变更只有同时满足以下条件才算完成：

1. 已实现所需行为，且没有扩展无关范围。
2. test 已覆盖变更，所有必要检查均通过。
3. `README.md` 和/或 `docs/` 已根据需要反映当前行为。
4. observable change 已在 `CHANGELOG.md` 的 `[Unreleased]` 下记录。
5. staged files 中不存在 secret、build artifact、cache 或无关 workspace file。
6. 最终交付说明包含行为、验证、文档以及剩余 risk 或 follow-up work。
