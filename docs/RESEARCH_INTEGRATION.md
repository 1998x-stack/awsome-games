# Fable 作品实体归并与代码审计（Evidence Lab）

**研究日期**：2026-11-16 的 Google Sheets 工作簿（当时 1,100 条来源记录）；2026-11-17 重新读取四个来源，变为 **1,118 条**。两种统计口径不能混为同一时点。

## 执行摘要

- **1,118 条来源记录 ≠ 907 个作品。** 当前有 907 个原帖实体线索（906 个唯一 X status ID 和 1 条没有 status ID 的孤儿），其中大多数只解决了帖子层身份，尚未证明为不同游戏。
- **83 个 GitHub URL ≠ 83 款网页游戏。** 包含原版、镜像、视频工具、Blender 插件、Windows 程序与 Pull Request。来源构成是 51 个原清单仓库 + 15 个附加链接仓库 + 17 个主链接仓库。
- **64 个源码作品映射**是第三方索引收录关系，不代表原作者归属或模型能力得到独立验证。
- **12 条反证**记录了模型版本冲突、社区镜像、错误仓库对应与多模型协作。

## 数据文件与来源

| 文件（均位于 data/research/v1/） | 记录数 | 含义 |
|---|---:|---|
| sources.json | 1,118 | 四个索引最新标题/作者/类别/原帖/URL；不复制视频、完整正文与源代码 |
| posts.json | 861 | 2026-11-16 的历史原帖归并快照 |
| entities.json | 907 | 2026-11-17 增量实体线索，保留未确认项目 |
| repositories.json | 83 | 候选仓库来源、角色、许可、技术及模型证据 |
| works.json | 64 | 游戏—仓库映射及社区提供的构建信息 |
| claims.json | 12 | 反证台账，分 SUPPORTED / PARTIALLY_SUPPORTED / DISPUTED / UNVERIFIED / REFUTED |
| readme_audits.json | 14 | 直接 README 审阅笔记 |
| html_audits.json | 12 | 代码头部、文件树及外部资源检查 |
| fable51.json | 9 | Fable 5.1 来源记录 |

主要原始来源：https://github.com/fengyiqicoder/awesome-fable-5.2、
https://github.com/ummydev/awesome-claude-fable-games、
https://github.com/mofa-si/awesome-fable-5-2-videos、
https://github.com/sandbase-lab/awesome-fable-5-2、
https://github.com/ygx2378/awesome-fable-5-2-games 及
[研究工作簿](https://docs.google.com/spreadsheets/d/1iIa0wVLh1ux-7y8VDlH9aZYsuIxpVBLz3LekmOwQtEY/edit)。

## 如何融合现有数据库

主 SQLite 文件 data/catalog.sqlite 的**原有 projects / repositories / links / prompts 等表保持不变**。新增 research_ 前缀的表：

1. research_source_records：原索引条目与原帖 ID。
2. research_posts：帖子层实体去重、候选原作实体与原始链接。
3. research_repositories：83 个候选仓库及模型归属置信度。
4. research_works：64 个原源码清单作品；入口、构建、外部依赖、提示词及人工参与分别记录。
5. research_claims：冲突台账。
6. research_project_links：对原有 155 个项目仅使用**完全一致的作品标题 + 同一个 GitHub 仓库**建立跨库关系，拒绝仅凭名字相似进行自动合并。
7. research_browser_runs：后续可持久化浏览器真实测试。当前没有第三方游戏实际通过的记录。

Python scripts/research_pipeline.py 实现幂等导入、URL 清洗、表结构、跨库映射及站点投影。运行：

    python3 scripts/build_catalog.py --check
    python3 scripts/check_catalog.py
    python3 scripts/build_site.py
    python3 -m unittest discover -s tests -v
    node --check site/assets/app.js
    node --check site/assets/research.js
    python3 -m http.server 8000 --directory site

然后访问 http://localhost:8000/research.html。主站 index.html 提供跳转链接；原有游戏卡片若能精确匹配研究 Work ID，还可直达对应证据页面。

## 归并规则

1. 相同 X status 数字代表**相同原帖**，不代表同一个游戏。
2. 同一个试玩 URL 是较强的演示实体线索；不同作者/多游戏页面或版本冲突需要复查。
3. 相同 GitHub 仓库可能存放多款游戏：Aquila / Dawnward、Tidebell / Mothlight / Misremember 是明确反例。
4. 标题相同、作者相同，只能创建候选，不能凭此自动合并。
5. 2026-11-17 新增的 46 个原帖先保留临时实体 ID，不能据此宣称新增 46 款游戏。
6. 静态 HTML 入口、单文件交付、真实浏览器加载、实际游戏交互通过是四种独立证据。未运行的游戏状态只能为 NOT_TESTED。

## 静态代码入口审查（文件树/README）

| 作品 | 公开仓库 | 审阅的入口 | 边界 |
|---|---|---|---|
| Saltline | realcodebear/saltline-fable-5.2 | index.html | 单 HTML 社区镜像；非原作者仓库 |
| SUBLEVEL 07 | wquguru/fable52-fps-repro | demos/04-fps/index.html | 多 demo、prompts/ 有提示词 |
| Ironvale | SharpWizard/ironvale | ironvale.html | 多模块，PROMPTS.md 有 21 条请求 |
| Aquila | GavinLOrio/Fable-5.2-random-game | index.html | 多源码文件打包的单 HTML |
| Dawnward | 同上 | rome/index.html | 与 Aquila 是两件作品 |
| Tidebell | hahaliu1029/fable5.2demo | tidebell/index.html | 同仓多个作品 |
| Mothlight | 同上 | mothlight/index.html | 同仓多个作品 |
| Misremember | 同上 | misremember/index.html | README 说明部分图片有 Codex 参与 |
| OUT OF REACH | alex-slovakia/out-of-reach | 无网页入口 | Unity/Windows，Fable 5.2 主要承担审阅 |

所有上述入口路径**只代表 GitHub 文件树或 README 核验，未实际执行游戏**。外部资源/人工贡献若来自作者 README，标记为作者自述，不能当独立可复现实验。

## 反证与错误归属

- [One Sweep](https://github.com/anstapnever/one-sweep)：作者 README 说 Opus 5.5；某社区索引说 Fable 5.5，标记 DISPUTED。
- [Kagami](https://github.com/Florencvv/kagami)、[RYŪ](https://github.com/seeconever/ryu)：README 自述 Fable 5.5，不是 Fable 5.2 单模型证据。
- [Castle Cinematic](https://github.com/Leonxlnx/castle-cinematic)：作者明确说明 Fable 5.2 与 Opus 5.5 子代理协作。
- [OUT OF REACH](https://github.com/alex-slovakia/out-of-reach)：实际为 Unity 作品，Fable 参与只读审查，不应当作 Fable 独立生成网页游戏。
- [Saltline](https://github.com/realcodebear/saltline-fable-5.2)：此 GitHub 仓库明确是第三方镜像。
- [Pelican](https://github.com/ChetasLua/pelican-riding-a-bicycle)：其关联的 mona-lisa-js 属于另一项目。
- [steel-webgpu PR #7](https://github.com/skild-ai/steel-webgpu/pull/7)：一条尚未合并的功能 PR，并非独立游戏仓库。

## 增量更新（生产式安全流程）

首次导入只需运行 build_catalog.py；后续扫描新来源时，使用以下命令：

    python3 scripts/refresh_research.py --dry-run
    python3 scripts/refresh_research.py --write
    python3 scripts/build_catalog.py --check
    python3 scripts/build_site.py
    python3 -m unittest discover -s tests -v

refresh_research.py 只下载四个指定 GitHub 索引的 JSON 元数据；绝不克隆或执行第三方项目源码。新识别的原帖进入未验证状态；已有实体的人工标注仍保留。旧的 data/research/v1/ 历史快照保持不变；审核完的新来源写入 data/research/current/，新旧来源数不得直接按无时间范围汇总。

若上游索引突然减少项目数，默认中止更新，需核实原因后才可添加 --allow-shrink。来源读取阶段不写入文件；所有来源全部成功后才使用临时文件与备份依次替换两个 current 快照，以尽量保护此前版本。正式生产建议再在 Git 版本控制中审核 JSON diff、保留校验哈希并分次发布。

**谨慎使用 --write：当前仅生成本地快照，尚未配置定时自动提交 GitHub，因此不会声称后续来源已经被自动持续监控。**

## 尚未解决的部分

多半原帖缺乏可核对的原版源码、Prompt 全文、Agent 操作日志、token 消耗、人工修改记录。静态文件树尚未实现对所有 83 仓库的**逐行**安全审计；也没有在此环境中完成 64 个游戏的独立浏览器操作。任何将它们写作“已实际可玩”的统计都是错误的。

独立 Chromium 测试方法、外部网络阻断及截图流程见 [BROWSER_SMOKE.md](BROWSER_SMOKE.md)。未经上游许可证和素材许可检查，不公开镜像游戏的可执行 HTML。

## 2026-11-17：核心完整性修复

**自动归并与人工审核必须隔离。** v1 的 64 项作品、83 个仓库与原帖集合是来源事实。原始 Prompt 的「未公开」「未发现公开」一律映射为 NOT_LOCATED，不因包含「公开」二字判为已发布。人类提示/编辑贡献不再复用「模型归属说明」，而是单独标注是否仅为作者自述。

### 审核文件与 SQLite 审计历史

`config/research_reviews.json` 是经人工确认的修正清单，可以对具体作品编号或原帖 ID 设置 APPROVED / DRAFT / REJECTED。只有状态 APPROVED 且附 HTTPS 证据链接才会覆盖网页展示字段。原始来源记录仍保留。用法：

    python3 scripts/review_evidence.py --file config/research_reviews.json
    python3 scripts/review_evidence.py --file config/research_reviews.json --apply
    python3 scripts/build_catalog.py --check
    python3 scripts/build_site.py

每次实际变更写入 `research_review_history`，重复导入同一审核记录不会增加历史记录。未审核的占位词不能被识别成真实人工编辑量或真实生成模型运行日志。

### 原子化来源更新

`python3 scripts/refresh_research.py --write` 只更新来源事实，不运行 GitHub 仓库代码。完整元数据对首先写入 `data/research/current/snapshots/<sha256>/`，然后一次性替换 `current/active.json` 指针。导入器验证路径、两份 JSON 的内容哈希与采集日期一致后才允许写入 SQLite。单独存在 sources.json 或 entities.json、或者哈希不匹配时直接失败，不回退到混合历史数据。

`research_source_records` 表现在严格反映当前来源快照的行数，而不是把已从上游移除的数据继续计入当前计数。旧 v1 仍作为冻结历史保留。相同 X status ID 才能归为同一原帖；同作者、同仓库或近似标题均不能证明是同一独立作品。

### 发布保护

新增两阶段的站点发布逻辑：仅复制经过许可批准的静态文件；排除密钥文件和非静态可执行脚本；拒绝符号链接；先计算容量；所有游戏与目录元数据准备成功后才替换线上工件。任何模拟的中途 I/O 失败都应恢复旧版本。`--preview-unapproved` 在 CI/Pages 环境直接拒绝。

CI 必须在 Pages 发布前先运行全部数据完整性、归并、发布沙箱及文件回滚测试。此流程不意味着第三方游戏已经实测通过。



### 固定源码证据修复（2026-11-18；从 PR #12 独立拆分）

GavinLOrio/Fable-5.2-random-game 在 [固定提交 447d0b5a 的 README](https://github.com/GavinLOrio/Fable-5.2-random-game/blob/447d0b5a7947fed9f2916c151c5aaf41522a96b1/README.md) 明确写明：Aquila → `rome/index.html`、Dawnward → `index.html`；该固定 Git 文件树均存在这两个入口。原研究映射反置，已纠正并纳入独立测试。这是源文件入口归属证据，**并非**浏览器交互或版权验证。
