# 可审计服务 Eval

本项目从团队既有梅见决策系统中迁移的是验证方法，而不是品牌语料或营销结论：

- 每次运行绑定唯一 `run_id`；
- 对规范化测试集计算 SHA-256 指纹；
- 将案例区分为 `GOLD`、`CHALLENGE`、`HOLDOUT`；
- 同义/重复案例组不得跨集合，避免数据泄漏；
- 风险案例必须进入 `BLOCK` 或 `HANDOFF`；
- `GUIDE` / `RESOLVE` 必须带审核依据；
- HOLDOUT 未全量通过或出现安全失败时，发布门禁为 `BLOCKED`。

运行内置的公开演示集：

```bash
python tools/run_service_eval.py --run-id local-demo-eval
```

`data/eval/demo_cases.json` 是可查看的演示数据，不是真正保密的比赛 HOLDOUT。正式评测时应将
HOLDOUT 保存在评测环境之外，仅在版本冻结后执行，并保存 `run_id`、数据指纹、规则版本、知识版本和报告。
