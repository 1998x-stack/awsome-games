# M4 · SourceAdapter 与元数据提案（安全边界）

- `scripts/source_adapters.py` 为四个已知、白名单中固定的 GitHub Raw JSON 数据源提供显式 `SourceAdapter` 配置与结构验证；不执行来源的代码。
- `scripts/refresh_research.py` 继续为旧工具保留 `normalize()` 和 `SOURCES` 接口；`prepare()` 经适配器只生成源记录及原帖候选，禁止自动模型审批。
- `scripts/propose_research_drift.py` 将新增、删除、修改的**来源标识**及计数写入 `data/research/proposals/latest.json`；不复制完整第三方内容，也不将变化写入活动数据库。
- `.github/workflows/research-proposal.yml` 每周及手动运行：如果 source record 有变化，生成一个唯一摘要哈希分支，创建 `Draft PR` 供人工审阅；不会向 main 自动合并，不变更 `data/research/current/active.json`、`config/research_reviews.json` 或发布授权。
- 若 GitHub 仓库策略不允许 Actions 自动创建 Pull Request，工作流明确失败；需要仓库管理员自行启用允许此操作的设置，不应通过个人 Token 绕过。
- 已在最新 main 查到的四类输入之外，`data/sources.json` 列出的其他来源不共用这四个 JSON schema；新增任何来源必须单独编写 `SourceAdapter`、验证数据字段、授权范围、速率限制和防丢数策略。
- 必须审计 PR 中的源记录变更，之后另开人工审阅 PR 运行 `refresh_research.py --write` 才能切换 current 指针。每个发布动作依旧遵循许可和游戏执行授权策略。

注意：变化摘要的 SHA256 是规范化字段内容的摘要，不是 Git commit SHA 或原始上游文件字节哈希；原始上游提交证据须在人工审阅环节补齐。
