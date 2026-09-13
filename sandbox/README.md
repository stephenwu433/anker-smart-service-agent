# Sandbox

此目录是本地实验区，用于 prototype、prompt 验证、data processing 试验和一次性分析。这里不使用
Docker，也不依赖额外 runtime。

## 目录结构

- `experiments/`：可复现的实验脚本，可以由 Git 跟踪。
- `output/`：实验输出，默认不被 Git 跟踪，仅保留目录结构。

运行示例：

```bash
scripts/sandbox.sh
```

运行指定实验：

```bash
scripts/sandbox.sh sandbox/experiments/example_health_check.py
```

实验验证稳定后，应把可复用逻辑迁移到 `src/`，在 `tests/` 中添加 test，并根据影响更新
`docs/` 和 `CHANGELOG.md`。不要让 production code import `sandbox/` 中的 module。

此 sandbox 只是代码与输出的目录隔离，不是 OS-level security boundary。未经信任的代码仍然不能
直接执行；涉及敏感数据时继续遵守仓库的 Security 与隐私规范。
