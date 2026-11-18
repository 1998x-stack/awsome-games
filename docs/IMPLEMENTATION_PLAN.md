# 实施计划与里程碑进度

**基线 SHA：** `ebab78e8f558abb37f7d02ff458c2edef1607801`
**分支：** `feat/pi-agent-baseline-hardening-20261117`
**更新日期：** 2026-11-17
**状态图例：** `VERIFIED`（真实执行并有证据）/ `IMPLEMENTED_NOT_VERIFIED`（代码落地未实测）/
`BLOCKED`（客观阻塞）/ `NOT_STARTED`

本次迭代范围：先完成一个**可复核的小闭环**——本地完整部署 + 真实缺陷修复 + 隔离能力落地，
把大规模数据归并和第三方实测留到下一批，并量化剩余工作。

---

## 批次 1：本地部署、基线与 P0/P1 缺陷修复 — `VERIFIED`

**验收标准：** 全部质量门禁绿；每个修复都有先失败的回归测试；权威数据库稳定 ID 与主表数量未意外变化。

| 交付物 | 文件 | 验证 |
|---|---|---|
| 本地基线报告 | `docs/LOCAL_BASELINE_2026-11-17.md` | 所有数字附 SQL/命令 |
| 跨页溯源链接修复 | `site/assets/{review,research,app}.js` | `tests/test_site_e2e.py`、`tests/test_site_link_policy.py` |
| 幂等导入（行号序列 + 时间戳） | `scripts/db.py` | `tests/test_hardening.py::SeedReproducibilityTests` |
| 证据来源往返保真 | `scripts/export_seed.py`、`scripts/db.py`、`data/seeds/legacy_projects.jsonl` | `tests/test_seed_provenance.py` |
| `--fresh` 删库前备份 | `scripts/build_catalog.py` | `tests/test_hardening.py::FreshRecreateSafetyTests` |
| 静态页面去除硬编码统计 | `site/index.html`、`site/research.html` | `tests/test_site_link_policy.py` |
| OS 级隔离执行器 | `scripts/isolation/{Dockerfile.smoke,run_isolated_smoke.sh}`、`.dockerignore` | `tests/test_isolation_harness.py` + 真实 `docker run --network none` |
| 文档与流程 | `AGENTS.md`、`docs/BROWSER_SMOKE.md`、`.github/workflows/validate.yml` | CI 等价命令本地全绿 |

**门禁结果：** 76 个单元测试通过（起始 56）；`build_catalog --check` / `check_catalog` /
`build_site` / `node --check` ×3 / `bash -n` 全部 exit 0。

**交付：** PR #9 与 PR #10 均已合并到 `main`；`main` 结束 SHA `3375af2af1f8c68658d606b709326df7f439bfcb`；
GitHub Pages 的 `build` 与 `deploy` 两个 job 均 success，线上页面全部 HTTP 200 并经真实 Chromium 点击验证。

---

## M1：实体归并与数据一致性 — `部分完成`

### 已完成

* **证据语义分离**：`research_posts.model_claim` 与
  `research_post_prompt_evidence.prompt_status` 分离（`NOT_LOCATED` 440、
  `INDEX_REPORTS_NOT_SHARED` 330、`INDEX_CLAIMS_SHARED_TEXT_NOT_CAPTURED` 70、`NOT_VERIFIED` 67）。
* **精确归并原则**：`research_project_links` 只用 `EXACT_REPO_AND_TITLE`，63 条；同名不自动归并。
* **冻结快照不可变**：`data/research/v1/*.json` 不被增量写回；来源快照两文件原子切换并校验 SHA-256。
* **人工审核独立层**：`research_work_reviews` / `research_post_reviews` / `research_review_history`
  独立于来源导入；重新导入不覆盖审核结论。
* **本轮新增**：修复"重建种子会伪造证据行"的缺陷——`project_evidence` 从 155 稳定在 155（此前
  每次重建翻倍到 310），且真实 `evidence_type`/`confidence` 可无损往返。
* **本轮新增**：修复幂等导入不幂等（`sqlite_sequence` 单调增长、`updated_at` 抖动）。
* **本轮新增**：入口映射可被审阅修正并可离线重放。`config/project_overrides.json` 现覆盖 19 个作品：
  11 个入口路径是页面 `<title>` 与目录标题**逐字对得上**才写入的（例：`XDracam/game/index.html`
  的 title 就是 `T-Minus`；`ONE_PROMPT_WORLDS` 的 13 个游戏里按标题精确映射到 `gameN/`，
  注意其根 `index.html` 只是菜单）；7 个声明为 `not_browser_based`（Unity/Godot/Rust/C，
  仓库内**没有任何 HTML**）；1 个声明为 `requires_build`（`%BASE_URL%` 与 `/src/main.tsx`
  证明是打包器外壳）。`needs_review` 19 → 0。
  新增 `--reclassify`：读已记录的 `repository_files` 重算映射，**无克隆、无网络**。
  声明式状态只允许 `DECLARED_REVIEWED_STATUSES` 中的值，且不能声明运行时结果（有回归测试守住）。
* **本轮新增**：`missing_static_assets()` 不再把 favicon/图标/字体算作缺失资源——运行时探针本就
  把它们 stub 成空响应，两侧标准对齐后 `aaron-sulbaran/jester` 不再因三个 favicon 被误判为
  `missing_assets`（实测真实原因是它自身的 TS module 在必需沙箱下被 CORS 拒绝），
  而 `bhoult/phone-games` 缺的 `engine.js`（功能性依赖）仍被正确报出。

### 未完成

* **904 条未归并原帖**的逐条一手证据审核（当前 907 中仅 3 条有 work 关联，63 条旧库精确映射）。
* `config/work_aliases.json` 的 `Last Return` / `Last Return（原 No Return）` 仍是 `CANDIDATE`。
* 别名、镜像、复刻、同作者多作品的多对多关系建模仍不完整。
* SQLite 二进制不可逐字节复现（逻辑内容已稳定）。

**下一步：** 为 907 条原帖建立分批审核工单（按 `kind_signal`、`match_status` 分层），
只允许带 HTTPS 一手证据的 `APPROVED` 条目升级；为每条 Post→Work 关系补充证据片段、抓取时间、审核人、冲突与回滚历史。

---

## M2：83 个候选仓库准入与代码级审计 — `NOT_STARTED`（仅路由）

### 已完成

* 83 个候选全部进入 `build_queue()`，其中 `research_only_repository_candidates` = 32（不在旧采集器内）。
* 分类仅作**审查路由**：`BROWSER_CANDIDATE_UNREVIEWED`、`MIRROR_NEEDS_ATTRIBUTION`、
  `NON_BROWSER_REVIEW`、`PR_OR_COMPONENT`、`RELATED_TOOL_OR_DIFFERENT_WORK`、`MIXED_MODEL_REVIEW`。
* `/review.html` 只读展示路由与原始证据链接。

### 未完成

* 83 个仓库**没有任何一个**完成逐行源码/依赖/许可证审计（当前仅为文件树 + 部分 README）。
* 未产出 `data/research/audits/*.json` 与 `docs/audits/*.md` 机读审计摘要。

**下一步（建议顺序）：** 先对已有 11 个已审静态入口的仓库做完整审计（固定 commit SHA、
外部请求清单、构建条件、许可证、镜像关系、风险），再按 `BROWSER_CANDIDATE_UNREVIEWED` 有序扩展。

---

## M3：隔离运行与结果回写 — `能力 VERIFIED / 第三方实测 123 个入口已测`

### 已完成

* **真正的 OS 级隔离执行器**：`scripts/isolation/Dockerfile.smoke` +
  `scripts/isolation/run_isolated_smoke.sh`。强制 `--network none`、只读根文件系统、
  **被审目录只读挂载**（页面无法篡改自身来源证据）、`--cap-drop ALL`、
  `no-new-privileges`、`--pids-limit`、内存/CPU 上限、非 root（uid 65534）、命名卷收报告。
* **启动前预检**：容器看不到入口时给出可执行提示，避免"空挂载"被误读为测试失败。
* **fail-closed 验证**：自编 fixture 无法冒充真实 `work_id` 导入，`research_runtime_evidence` 保持 0 行。
* 导入器仍要求 40 位 commit SHA、入口与已审 `entry_path` 一致、内容寻址 `evidence_id`、重复导入幂等。
* **分离式批量模式**（`--detach` / `--collect` / `--name`）：并行分片各占一个容器，
  清单与报告目录按容器名分域，容器不能带 `--rm`（否则报告取不回来）。
* **全量实测 123 个入口（0 未测）**，覆盖 32 个仓库。产物：
  `data/reports/repo-survey-2026-11-18.json`（含逐条指纹、可用 `--manifest/--reports` 重放）。
* **输入归因规则**（`scripts/input_attribution.py`）：探针与离线汇总器**共用同一份实现**，
  所以历史报告能用修正后的规则重判而无需重跑浏览器。
* **把实测结论写进权威库的写入者**（`scripts/apply_survey_to_catalog.py`）：
  在此之前库里那些 `sandbox_incompatible` / `runtime_*` 行**没有任何脚本能产生**，只有"保留"。
  新写入者按构造 fail-closed：只写限制性状态、拒跑不合格证据文件、绝不弱化既有结论、记录证据 sha256。
* **失败分类词表**：把"产物失败"拆成需要不同决定的类别（需 CDN / 需网络 / 沙箱不兼容 /
  第三方信标 / 设备传感器 / 输入无法归因 / 驱动被阻塞 / 渲染器崩溃=**环境上限**）。

### 未完成 / 阻塞

* **8 个入口在本机环境内测不出结论**：4 个阻塞驱动（外部 `timeout -s KILL` 在 60 秒终止，
  两批独立运行可重现），4 个驱动侧异常（其中渲染器崩溃在本机 2 CPU / 4 GB 的 Docker VM 上
  属环境上限）。它们**不**被写成对产物的判断，只记 `runtime_driver_timeout` 或不记状态。
* **仍然没有 `GAMEPLAY_VERIFIED`**，而且这次是刻意为之：机器能做出的最强主张只是
  `input_responsive`（可归因的输入响应）。
* 未实现"每个游戏真实交互预期"的行为断言（点击/键盘/触控 -> 预期状态变化）；
  因此无人能拿到 `GAMEPLAY_VERIFIED`，站点上也就不存在这个标签。
* WebRTC/UDP/WebGPU 的浏览器兼容性矩阵未测。第三方程序仍**必须在 OS/网络隔离内**运行。

**下一步：** 对 8 个未能测出的入口在更宽裕的配置下各重试一次（已完成一次，见交接报告）；
为已可归因的 4 个作品补写逐游戏交互断言，作为从 `input_responsive` 迈向人工确认的证据。

---

## M4：增量发现、审核与 CI/CD — `部分完成`

### 已完成

* `.github/workflows/research-sync.yml` 每日 UTC 03:17 只读漂移检查，不写回 main、不克隆、不部署。
* 来源缩减触发失败并保留运行制品。
* CI 门禁：`validate.yml` 现在包含 `compileall`、全套单测、三个前端 `node --check`、
  `bash -n scripts/*.sh scripts/isolation/*.sh bootstrap.sh`、`check_catalog`、`build_site`。

### 未完成

* 4 个结构化上游之外，`data/sources.json` 列出的更多来源未接入 `SourceAdapter`。
* 无定期 PR 提案、无审查签核、无链接有效性持续监测、无数据迁移框架。
* 未扩充故障注入/XSS/CSV 公式注入/路径遍历/symlink 的**端到端**回归（部分已有）。

**下一步：** 建立 `SourceAdapter` 抽象与数据版本表；增加仅元数据的自动化 PR 提案；
补充 CSV/路径/symlink 的端到端安全回归。

---

## M5：统一研究网站与审核工作台 — `部分完成`

### 已完成

* 三个页面（目录 / Evidence Lab / Review Queue）真实加载，**0 page error、0 console error**。
* `/review.html` 严格 `textContent`、无 `innerHTML`、`noopener noreferrer`、`referrerPolicy`。
* 独立状态分离：来源收录 / 入口已定位 / 浏览器加载 / 实际交互 / 发布授权 分别呈现，无"可玩"单一标签。
* 空结果与加载失败提示、加载更多、按类型/状态筛选与 CSV 导出（含公式注入转义）。
* **本轮修复**：Review Queue → Evidence Lab 的溯源跳转此前渲染为死链 `<span>`，现已可用且保持相对路径。
* **本轮修复（后续）**：链接可点后仍会**新开标签页**（`makeLink()` 无条件 `target="_blank"`）；现仅跨源链接开新标签页，同源溯源就地导航。已在线上真实点击验证。

### 未完成

* 无全设备视觉验收截图证据。
* 无跨原帖的多对多实体导航图；Review Queue 无 CSV 导出。
* 无真正的交互式审核后台（当前只读，写入走 `config/research_reviews.json` + CLI）。

**下一步：** 增加移动端/键盘可达性 E2E 与截图归档；为 Review Queue 增加导出；
实现 Post↔Work↔Repository↔Audit↔Runtime 的双向可点击导航。

> 经验：任何“跳转/导航”类断言必须用真实用户手势（`click()`）。用 `page.goto()` 直接导航会掩盖真实的交互缺陷。

---

## 剩余工作的优先级建议

1. **M2 的 11 个已审入口仓库完整审计**（可复核、不涉及运行第三方代码）。
2. **M1 的分批原帖审核工单**（把 907 条量化到可执行的批次）。
3. **M5 的移动端/无障碍 E2E 与截图证据**。
4. **M4 的 `SourceAdapter` + 元数据 PR 提案**。
5. **M3 第三方实测**——仅在取得人工确认后。
