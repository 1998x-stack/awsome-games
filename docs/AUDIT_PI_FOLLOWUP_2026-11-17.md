# Pi Agent 迭代复核 · 2026-11-17（固定基线）

审计对象：[main @ 687e56a564bba2f95c0411b5b3bc2357f481ceae](https://github.com/1998x-stack/awsome-games/tree/687e56a564bba2f95c0411b5b3bc2357f481ceae)。本次在独立 PR #12 提交代码，不改变审计主基线。必读参考：`docs/PI_AGENT_HANDOFF.md`、`data/reports/pi-agent-latest.json`、`docs/LOCAL_BASELINE_2026-11-17.md`、`docs/IMPLEMENTATION_PLAN.md`。

## 证据核对与真实状态

| 单位 | 基线指标 | 查验方式 |
|---|---:|---|
| 传统作品目录 projects | 155 | SQLite `SELECT COUNT(*)`；最新 CI 构建保持 |
| 传统仓库 repositories | 54 | SQLite `SELECT COUNT(*)`；最新 CI 保持 |
| research_source_records | 1,118 | 2026-11-17 Pi baseline 的实际 SQLite 结果 |
| research_posts | 907 | 906 个真实 X 状态 ID + 1 个 orphan；**不是 907 个游戏** |
| research_works | 64 | 社区来源映射；不等于已验证原创作品 |
| research_repositories | 83 | 候选链接；不得合并为传统 54 个仓库的统计口径 |
| research_project_links | 63 | 基线的精确匹配候选；不是 63 份经复核原创性 |
| 已审静态入口映射 | 11 | 源码入口定位，**非游戏运行证据** |
| research_runtime_evidence | 0 | 未经人工确认，没有第三方实测，不得冒充有 |
| 生产发布游戏 | 0 | 最新 CI `published_games: 0`；无源代码再分发批准 |

初始提交的旧 `data/catalog.sqlite` 无任何 `research_*` 表，研究库必须由冻结 JSON 经构建导入。Pi 前轮已修复相关研究层落盘，但 SQLite 二进制文件不是逐字节可重建；比较逻辑数据而非强制字节哈希。

## P0/P1 问题与实际补丁

1. **真正的作品入口错绑（P0，已修复）**：固定上游 [GavinLOrio 仓库 README](https://github.com/GavinLOrio/Fable-5.2-random-game/blob/447d0b5a7947fed9f2916c151c5aaf41522a96b1/README.md) 写明 Aquila=`rome/index.html`，Dawnward=`index.html`，原 `REVIEWED_ENTRIES` 正好颠倒。本 PR 修正并给出独立回归测试。
2. **来源 URL 上的证据丢失（P1，已修复）**：`export_seed.py` 原来按 URL 建 dict 取最后一条；两个有效 `evidence_type` 会被覆盖。现保留列表并兼容旧版单项对象，测试同 URL 多证据类型保持完整并防止伪造重建占位符入库。
3. **关联变化未更新时间戳（P1，已修复）**：`db.py` 原 CASE 对所改写的 `projects` 标量字段判断完整，但 `project_categories` 关系单独变化不会增加 `updated_at`。补丁仅在分类真正变化时更新时间，同时保持幂等性；运行状态由采集器独立处理，没有用 seed 覆盖。
4. **任意 HTTPS 可当审核证据（P1，已收紧）**：`review_evidence.py` 要求 APPROVED 提供 reviewer、reviewer_note、证据类型，且证据 URL 能关联到原始 X 帖子或固定 commit 下的该作品 GitHub blob。该绑定仅验证关联身份，不证明文本内模型身份为真；仍需人工解释引文、作者身份及反证。
5. **伪造 commit 关联测试报告（P1，已收紧）**：`import_browser_report.py` 不再只认 40 位 SHA 字符串，还根据静态审计清单校验入口 Git blob 身份；成功加载报告必须附截图并保存 SHA256。**仍未执行第三方程序。**
6. **没有可分派的原帖任务（P1，已分批）**：按现有 kind_signal、match_status、URL 线索精确分成 40 批，每批不超过 25 条；全部 `UNREVIEWED`，没有自动归并。

## M1 · 精确审核批次

| 工单路由 | 原帖数 | 主要动作 |
|---|---:|---|
| 已映射，需独立复核 | 2 | 核对 source ↔ work 原作者及反证 |
| 现有候选 | 1 | 不能自动批准 |
| 未归并 + 仓库 URL | 19 | 优先验证源码归属、镜像、复刻 |
| 未归并 + 游戏信号 + play URL | 175 | 核对可玩页面及一帖多作品 |
| 未归并 + 其他信号 + play URL | 6 | 先确定是否游戏 |
| 未归并 + 游戏信号、无 URL | 99 | 查作者原帖和实际入口 |
| 未归并 + 其他信号、无 URL | 33 | 先确认类别 |
| 未归并 + 视频/工具/未分类、无 URL | 572 | 分类消歧，不强造作品 |

数据：`data/research/review_batches/2026-11-17.json`；运行生成器：`python scripts/make_post_batches.py --check`。完整规则在 `docs/POST_REVIEW_BATCHES.md`。

## M2 · 11 个入口扫描与 7 个仓库文件树

上游固定 commit、HTML Git blob 的**全文静态检查**、仅词法命中标记、明确的源码归属/许可证限制：

| 仓库 | 固定 commit 前缀 | Git 文件数 | 关键未决风险 |
|---|---|---:|---|
| realcodebear/saltline-fable-5.2 | 09c51774 | 2 | README 明确自述第三方镜像，缺仓库 LICENSE，作者授权尚未证明 |
| wquguru/fable52-fps-repro | a7e1df3c | 34 | MIT，非原作而是复现；SUBLEVEL 07 入口引入 jsDelivr CDN |
| SharpWizard/ironvale | 41672ef3 | 43 | 无 LICENSE 标记；第三方模型/Three.js 与 CDN 备用路径 |
| DNDNoob/EmberDeep | 53db7db9 | 33 | WebRTC、Trystero/Nostr 公共中继、麦克风/语音网络 |
| GavinLOrio/Fable-5.2-random-game | 447d0b5a | 25 | Aquila/Dawnward 双作品入口已纠正；构建条件和授权需复核 |
| S77FFY/daedalus | be77f2f3 | 4 | GoatCounter 统计脚本；未发现仓库 LICENSE |
| hahaliu1029/fable5.2demo | 97710fad | 709 | Apache-2.0 仓库元数据不等于媒体权利；MISREMEMBER README 承认 Codex 图片 |

总计 850 条 Git 文件记录；11 个入口已全文分析，剩余 212 个文字/源码文件只完成**树元数据**核对，另 627 个二进制/未知类文件只做 metadata inventory，包含图片/音频/模型等。不能宣称完成完整依赖或素材版权审查。

已生成：11 个 `data/research/audits/F52-Wxxx.json` 和 11 个 `docs/audits/F52-Wxxx.md`，另有 7 个 `data/research/audits/repos/<repo>.json` 完整文件树清单。后续 Pi 可用 `scripts/audit_local_source_tree.py` 对固定 commit 的本地 Git 对象逐文件只读扫描所有可读文本并输出 SHA256/外部域名/潜在代码执行入口；文档 `docs/M2_OFFLINE_SOURCE_AUDIT.md`。

## M3 · 人工确认门槛

- `research_runtime_evidence=0`；`GAMEPLAY_VERIFIED=0`；并未取得第三方运行授权，**不执行任何上游 HTML/JS**。
- 只有在人工确认某个**具体项目/具体 commit**及 OS 级隔离策略后，才允许在 disposable `--network none` 容器内开始真实 HTML 载入/交互测试。
- 对 Emberdeep（WebRTC/语音）尤其不能仅凭 Playwright 的 route 防火墙断言网络隔离。

## M4 · 安全 SourceAdapter 与 PR 提案

- 旧的四个 JSON 上游现在通过显式 `SourceAdapter` 验证数据字段与集合结构。
- 新 `scripts/propose_research_drift.py` 只生成 source IDs / 数量 / 内容摘要，没有模型 APPROVED、没改 `data/research/current/active.json`。
- `.github/workflows/research-proposal.yml` 每周生成**候选 Draft PR**，不自动合并；GitHub Actions 是否允许建立 PR 尚需实际调度验证。它不是当前证据快照的自动升级器。
- `data/sources.json` 其余来源的专用适配器仍未编写；不要把网页 HTML 列表偷换成四种 JSON 格式。

## M5 与后续要点

现有目录/研究/审核工作台的真实点击导航前轮已修复。本 PR 新审计报告**尚未完整接入网站的 Post ↔ Work ↔ Repository ↔ Audit ↔ BrowserRun 全链路**；下一轮应新增证据级链接和任务过滤，保留全部 UNVERIFIED/NOT_TESTED/NOT_AUTHORIZED 状态。

## 验证结果与限制

本轮最后提交 [Validate catalog CI](https://github.com/1998x-stack/awsome-games/actions/runs/44051665452)：89 项测试运行、3 项因 GitHub runner 无 Playwright 跳过，其余通过；`projects=155`、`repositories=54`、`problems=[]`、`published_games=0`。Python 编译、目录/数据构建、三项前端 JS 的 node --check、Shell bash -n 也均获 CI 通过。

用户本地 Pi 之前以项目虚拟环境和 Chromium 完成真实 E2E，此轮远程设备均离线，因此没有声称重新跑本机浏览器/第三方代码。新工作流的定时触发、草稿 PR 发布权限和完整上游源码扫描仍未完成实测。

## 下一轮执行顺序（精确）

1. **#5** 在 Pi 本地获取固定七个 Git commit，按 `docs/M2_OFFLINE_SOURCE_AUDIT.md` 运行只读全源码扫描；审阅所有网络 API、资源链接、第三方脚本和许可证来源；更新每个报告的 *scan coverage*。
2. **#4** 从 `P10_REPO_LEADS` 的 19 条高价值原帖开始，逐条寻找作者 HTTPS 一手证据、镜像声明及模型来源；需要人工批准，不增添未经证实的游戏。
3. **#6** 在第 1 步完成、用户单独授权具体固定项目后，选择网络依赖最少且权利明确的入口，在 `--network none` 测试交互和截图，保证证据表最初仍是零。
4. **#7** 手动触发一次元数据 Proposal 工作流，验证 GitHub 权限、去重、缩减防护、Snapshot 指针不被写；补齐剩余来源的独立 Adapter。
5. **#8** 以只读 JSON 建立关联审核详情、截图哈希和报告深链；为 Chrome 真实点击、触摸设备与键盘可达性加回归测试。
