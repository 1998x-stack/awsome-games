# PI Agent 交接报告 · 2026-11-17

给下一位 ChatGPT / 维护者阅读。**每个结论都有命令、SQL、代码路径或 GitHub URL 支撑。**
凡未执行的验证一律写 `NOT_TESTED` / `BLOCKED`，不猜数字。

---

## 1. Environment & Git

| 项目 | 值 |
|---|---|
| 执行日期 (UTC) | 2026-11-17 |
| OS | macOS (Apple Silicon) |
| 项目 Python | 3.12.15（`/opt/homebrew/bin/python3.12`）；系统 `python3` 为 3.9.6，**低于 README 要求的 3.10+** |
| Node.js | v26.13.1 |
| Git | 2.54.0 (Apple Git-157) |
| Docker | 29.9.1，daemon = Ubuntu 24.04.4 LTS |
| 仓库 | `https://github.com/1998x-stack/awsome-games` |
| 起始 SHA | `ebab78e8f558abb37f7d02ff458c2edef1607801` |
| 起始状态 | 工作树**干净**，`0 ahead / 0 behind origin/main`，无 stash |
| 工作分支 | `feat/pi-agent-baseline-hardening-20261117` |
| 结束时 SHA | 见文末"本轮提交"一节 |
| PR | https://github.com/1998x-stack/awsome-games/pull/9 |
| CI | https://github.com/1998x-stack/awsome-games/actions/runs/44042084460 — `Validate catalog` = **success** |

保护现状：`data/catalog.sqlite` 已备份到 `/tmp/awsome-games-backup/catalog.sqlite.baseline-ebab78e`
（SHA-256 `602a2a80a77b0e95b883eb419006a8017ee4cca5d857a31c4a0712802b56d5fa`）。
未执行 `reset --hard` / `clean -fd` / `stash`，未触碰用户其它文件。

---

## 2. Baseline vs Current Metrics

所有数字都用 `python3 scripts/build_catalog.py --check` + `python3 scripts/check_catalog.py`
+ 直接 SQL 现算，**不是**从 README 复制。

| 指标 | 起始值 | 结束时 | 来源 / 方法 | 差异说明 |
|---|---:|---:|---|---|
| `projects` | 155 | 155 | `SELECT COUNT(*) FROM projects` | 未变（符合预期） |
| `repositories` | 54 | 54 | `SELECT COUNT(*) FROM repositories` | 未变 |
| `project_repositories` | 150 | 150 | `SELECT COUNT(*) FROM project_repositories` | 未变 |
| `links` | 64 | 64 | `SELECT COUNT(*) FROM links` | 未变 |
| `prompts` | 76 | 76 | `SELECT COUNT(*) FROM prompts` | 未变 |
| `evidence_sources` | 81 | 81 | `SELECT COUNT(*) FROM evidence_sources` | 未变 |
| `project_evidence` | 155 | **155** | `SELECT COUNT(*) FROM project_evidence` | 起始提交的 DB 是 155；**重建会变成 310**（缺陷，已修） |
| `research_source_records` | 表不存在 | 1118 | `SELECT COUNT(*)` | 起始提交的 DB **没有** `research_*` 表 |
| `research_posts` | 表不存在 | 907 | `SELECT COUNT(*)` | 同上；906 精确 X ID + 1 `orphan:` |
| `research_works` | 表不存在 | 64 | `SELECT COUNT(*)` | 同上 |
| `research_repositories` | 表不存在 | 83 | `SELECT COUNT(*)` | 同上 |
| `research_claims` | 表不存在 | 12 | `SELECT COUNT(*)` | 同上 |
| `research_project_links` | 表不存在 | 63 | `SELECT COUNT(*)`，全部 `EXACT_REPO_AND_TITLE` | 同上 |
| 已审静态入口 | — | 11 | `entry_status='TREE_PATH_REVIEWED_NOT_EXECUTED'` | 未变 |
| `research_runtime_evidence` | 0 | **0** | `SELECT COUNT(*)` | **没有任何第三方游戏被验证** |
| `research_work_reviews` / `post_reviews` | 0 / 0 | 0 / 0 | `SELECT COUNT(*)` | `config/research_reviews.json` 仍为空 |
| 发布到站点的游戏 | 0 | 0 | `build_site.py` → `published_games` | 授权白名单仍为空 |
| 单元测试数 | 56 | **75** | `python -m unittest discover -s tests -v` | +19 个回归测试 |

### 口径警告（必须保持）

* 1118（来源记录）、907（原帖线索）、83（候选仓库）、64（工程映射）是**四种不同粒度**，不可相加、不可称"游戏数"。
* 907 条中只有 3 条有 `work_id`；63 条是"旧目录↔研究层"的精确仓库+标题映射。
* `export_projection()` 对每个 work 都输出 `execution_verified: false`；`GAMEPLAY_VERIFIED` 数量为 0。

### 起始提交的 DB 不完整（重要）

`sqlite3 <baseline>.sqlite ".tables"` 显示**只有** `projects/repositories/links/prompts/...`，
**没有任何 `research_*` 表**。研究层是首次运行 `build_catalog.py` 时由 `data/research/v1/*.json`
创建并填充的，所以直接读仓库里的 `.sqlite` 得不到完整研究库。本 PR 提交了完整物化版本（1.34 MB）。

---

## 3. Implemented Changes（按里程碑）

### M1 — 实体归并与数据一致性

| 文件 | 变更 | 风险 | 状态 |
|---|---|---|---|
| `scripts/db.py` | AUTOINCREMENT 表改用守卫式 `INSERT ... SELECT ... WHERE NOT EXISTS`；`projects.updated_at` 仅内容变化时推进；新增 `SYNTHETIC_EVIDENCE_TYPES`；`seed_database` 优先使用每来源 `evidence_by_source`，且**永不**把合成标记落成证据行 | 低（语义保持） | `VERIFIED` |
| `scripts/export_seed.py` | 保留真实 `evidence_type`/`confidence`，不再硬编码 `sqlite_snapshot_reconstruction` | 低 | `VERIFIED` |
| `data/seeds/legacy_projects.jsonl` | 由基线 DB 重新生成，携带真实来源证据类型（155 条，稳定 ID 不变） | 中（数据文件） | `VERIFIED` |
| `scripts/build_catalog.py` | `--fresh` 前用 SQLite backup API 写 `data/backups/` 并校验完整性，失败则拒绝重建 | 低 | `VERIFIED` |

### M2 — 候选仓库准入

**本轮无实质推进。** 83 个候选仍只有路由分类（`BROWSER_CANDIDATE_UNREVIEWED` 等），
没有逐行源码、依赖或许可证审计。状态：`NOT_STARTED`。

### M3 — 隔离运行与结果回写

| 文件 | 变更 | 状态 |
|---|---|---|
| `scripts/isolation/Dockerfile.smoke` | 固定 `playwright==1.65.2` + Chromium 的可丢弃运行镜像；不烘焙任何仓库源码或凭据 | `VERIFIED` |
| `scripts/isolation/run_isolated_smoke.sh` | 强制 `--network none`、只读根文件系统、**被审目录只读挂载**、`--cap-drop ALL`、`no-new-privileges`、`--pids-limit`、内存/CPU 上限、uid 65534、命名卷收报告、启动前挂载预检 | `VERIFIED` |
| `docs/BROWSER_SMOKE.md` | 记录隔离边界、用法与实际验证范围 | `VERIFIED` |
| `tests/test_isolation_harness.py` | 6 个契约测试，防止隔离标志被悄悄削弱 | `VERIFIED` |

### M4 — 数据自动化与 CI

| 文件 | 变更 | 状态 |
|---|---|---|
| `.github/workflows/validate.yml` | 补 `compileall`、全套单测、三前端 `node --check`、`bash -n scripts/*.sh scripts/isolation/*.sh bootstrap.sh` | `VERIFIED`（CI run 绿） |

### M5 — 统一研究网站与审核工作台

| 文件 | 变更 | 状态 |
|---|---|---|
| `site/assets/review.js` | **修复死链**：`safeUrl` 改为 `new URL(value, document.baseURI)`，同源目标保持相对路径（兼容 GitHub 项目 Pages 子路径），拒绝内嵌凭据 | `VERIFIED` |
| `site/assets/research.js` | 同样的解析与凭据校验 | `VERIFIED` |
| `site/assets/app.js` | 同上的凭据校验 | `VERIFIED` |
| `site/index.html`、`site/research.html` | 移除硬编码的"83 个仓库"与研究快照日期 | `VERIFIED` |

---

## 4. Commands Actually Executed

全部在本机真实执行，日志见 `/tmp/ag-e2e/gate/gate.log`。

| 命令 | 退出码 / 结果 |
|---|---|
| `.venv/bin/python -m unittest discover -s tests -v` | **exit 0 — Ran 75 tests, OK**（起始 56） |
| `.venv/bin/python scripts/build_catalog.py --check` | exit 0 — `integrity_check: ok`，`foreign_key_errors: 0`，`projects: 155` |
| `.venv/bin/python scripts/check_catalog.py` | exit 0 — `problems: []` |
| `.venv/bin/python -m compileall -q scripts tests` | exit 0 |
| `.venv/bin/python scripts/build_site.py` | exit 0 — `{"projects":155,"repos":54,"published_games":0,"published_repos":0,"site_bytes":1530556}` |
| `node --check site/assets/app.js` / `research.js` / `review.js` | 全部 exit 0 |
| `bash -n scripts/*.sh scripts/isolation/*.sh bootstrap.sh` | exit 0 |
| `.venv/bin/python scripts/review_evidence.py` | exit 0 — `{"review_entries":0,"written":0}` |
| `docker build -f scripts/isolation/Dockerfile.smoke -t awsome-games-smoke .` | exit 0 — 镜像 1.93 GB |
| `bash scripts/isolation/run_isolated_smoke.sh --root .cache/isolated-stage --entry demos/fps/index.html --out .cache/iso-reports` | exit 0（见第 5 节） |
| `git push -u origin feat/pi-agent-baseline-hardening-20261117` | exit 0 |
| `gh pr create ...` | PR #9 |
| `gh pr checks 9` | `validate  pass  14s` |

### 复现关键缺陷的命令（修复前后对比）

```bash
# 缺陷 1：证据来源被伪造
sqlite3 data/catalog.sqlite "SELECT COUNT(*) FROM project_evidence;"     # 修复前 310 / 修复后 155
grep -c sqlite_snapshot_reconstruction site/data/catalog.json            # 修复前 155 / 修复后 0

# 缺陷 2：幂等导入不幂等（连续两次构建的逻辑 dump 差异）
python3 scripts/build_catalog.py --check && cp data/catalog.sqlite /tmp/a.sqlite
python3 scripts/build_catalog.py --check && cp data/catalog.sqlite /tmp/b.sqlite
for f in a b; do sqlite3 /tmp/$f.sqlite .dump > /tmp/$f.sql; done
diff /tmp/a.sql /tmp/b.sql | wc -l                                       # 修复前 10 / 修复后 0

# 缺陷 3：跨页溯源跳转是死链（真实 Chromium）
# document.querySelectorAll('#queue-results .lab-card-foot a').length    # 修复前 1 / 修复后 2
```

---

## 5. Runtime Evidence

| 项目 | 值 |
|---|---|
| 执行环境 | `docker run --network none --read-only --tmpfs /tmp --user 65534:65534 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 1g --cpus 1` |
| 被测对象 | **本仓库自编写的无害 fixture**（`.cache/isolated-stage/demos/fps/index.html`），**不是**第三方游戏 |
| 入口 SHA-256 | `5af5f546bb8bd5090e70747d15a82e8817af0a6ddf06608f136331d2ba7cac87` |
| 浏览器 | Chromium headless shell 159.0.8154.6（Playwright 1.65.2） |
| 报告 | `.cache/iso-reports/smoke.json` — `status: BROWSER_LOAD_CHECKED`、`iframe_isolation: true`、`frame_body_loaded: true`、`gameplay_verified: false`，console/blocked/failed/http 错误均为空 |
| 截图 | `.cache/iso-reports/smoke.png`（SHA-256 `5a91a8c388c78289ebae06c5746de054d3e043eb760ffaf02199706a234345c0`） |
| 自编 fixture 交互探针 | `gameplay_interaction: PASS`、`parent_document_access: BLOCKED`、`third_party_games_verified: 0` |
| **第三方游戏** | **`NOT_TESTED`（0 个）**——未克隆、未运行任何第三方源码 |
| `research_runtime_evidence` | 0 行 |

### fail-closed 验证（重要）

用自编 fixture 冒充真实 `work_id=F52-W012` 导入：

```
python3 scripts/import_browser_report.py --work-id F52-W012 --repo-commit 0000...0000 \
  --root .cache/isolated-stage --report .cache/iso-reports/smoke.json \
  --browser-version '...' --environment '...'
→ ValueError: Missing/unsafe staged entry   (exit 1)
sqlite3 data/catalog.sqlite "SELECT COUNT(*) FROM research_runtime_evidence;"  → 0
```

原因：入口必须与 `research_works.entry_path`（已人工审阅的入口）一致且锁定 40 位 commit SHA，
自报报告无法获得认证。这是**设计正确**的证据，不是失败。

### 网站 E2E（真实 Chromium，非 mock）

在 `127.0.0.1` 上以 HTTP 服务遍历三个页面，并拦截所有外部请求：

* `index.html` / `research.html` / `review.html`：**0 page error、0 console error、0 被阻断的外部请求**
* 统计卡片：155 / 54 / 59 / 0（与 `summary` 一致）；研究层 1,118 / 907 / 64 / 83 / 12
* 交互：搜索、四类筛选、空结果提示、加载更多（36 → 72 卡片）、`?work=` 与 `?kind=repositories&id=` 深链详情、`Escape` 关闭、CSV 导出下载
* 游戏 iframe sandbox 仍为 `allow-scripts allow-pointer-lock allow-forms allow-modals`，**无 `allow-same-origin`**

已固化为 `tests/test_site_e2e.py`（Playwright 缺失时自动 skip）与 `tests/test_site_link_policy.py`。

---

## 6. Security & Licensing

| 项目 | 结果 |
|---|---|
| 第三方代码是否被运行 | **否**。仅在隔离容器中运行本仓库自编写的 fixture |
| 是否执行上游 `npm install` / `build` / 二进制 | 否 |
| 隔离环境是否合规 | 是：`--network none`（OS 级网络命名空间）、只读根文件系统、**被审目录只读挂载**、`--cap-drop ALL`、`no-new-privileges`、非 root、资源上限 |
| `config/publication_approvals.json` | **未修改**，仍为 `approved_repositories: []` |
| 许可证批准白名单 | **未修改** |
| 敏感信息 | `git diff --cached` 全量扫描：无 API Key / Token / Cookie / `.env` / SSH Key；仅有变量名 `password`/`username` 出现在 URL 校验代码与测试断言中 |
| `.env` / 凭据是否进入镜像 | 否；镜像不烘焙任何仓库源码或凭据（有契约测试） |
| 历史冻结 JSON | `data/research/v1/` **未改动** |
| 授权风险 | 未新增任何再发布授权；无许可证争议处理 |
| 提交体积 | `data/catalog.sqlite` 319 KB → 1.34 MB（研究层物化）；无大文件误提交（无 `games/_repos`、无第三方源码） |

---

## 7. Git / CI / Deployment

| 项目 | 值 |
|---|---|
| commit | `fix(M1/M3/M5): restore provenance fidelity, idempotent rebuild and cross-page evidence links` |
| 分支 | `feat/pi-agent-baseline-hardening-20261117` |
| 推送 | 成功（`* [new branch]`），**未强推** |
| PR | https://github.com/1998x-stack/awsome-games/pull/9 |
| CI job | `Validate catalog` = **success**（14 s）· https://github.com/1998x-stack/awsome-games/actions/runs/44042084460 |
| 合并 | **尚未合并**（见下） |
| GitHub Pages | 本 PR 未触发部署（`pages.yml` 只在 push 到 `main` 或手动触发时运行）。**未声称任何生产上线成功。** |
| 线上可访问性核实 | `NOT_TESTED`（需合并后触发 Pages workflow 才能核实） |

### 关于合并的准确状态

CI 全绿、无安全/许可证阻塞、未发现分支保护禁止。但**本报告作者在本轮没有执行合并**，
理由：合并会触发 GitHub Pages **生产部署**（属"生产权限变更/不可逆操作"），
按硬约束 §1.9 应先取得人工确认。授权已具备时，合并命令为：

```bash
gh pr merge 9 --squash --delete-branch
gh run list --workflow=pages.yml --limit 3          # 核实 build 与 deploy 两个 job 的真实结果
```

合并后必须区分"build 成功"与"deploy 成功"，并单独核实线上页面可访问性。

---

## 8. Open Issues & Blockers

| 严重度 | 问题 | 复现 / 证据 | 修复建议 | 关联 Issue |
|---|---|---|---|---|
| **Blocker** | 64 个研究作品**全部** `NOT_TESTED`，`GAMEPLAY_VERIFIED` = 0 | `SELECT COUNT(*) FROM research_runtime_evidence` → 0；本地无第三方源码快照 | 取得人工确认后，在 `scripts/isolation/run_isolated_smoke.sh` 中按已审 `entry_path` 运行；逐游戏补交互断言 | #6 |
| **Blocker** | 11 个已审静态入口无法实际运行 | 入口文件不在本地，`games/_repos` 不存在 | 先完成 M2 的只读源码获取与许可证核对，再运行 | #5 #6 |
| 高 | 83 个候选仓库**零**逐行源码/依赖/许可证审计 | `docs/IMPLEMENTATION_PLAN.md` M2 节 | 先做已有 11 个入口的仓库，固定 commit SHA 产出 `data/research/audits/*.json` | #5 |
| 高 | 904 条未归并原帖无一手证据审核 | 907 条中仅 3 条有 `work_id` | 按 `kind_signal`/`match_status` 分批建立审核工单；只允许 HTTPS 一手证据升级 | #4 |
| 中 | SQLite **二进制**不可逐字节复现 | 两次运行经 `VACUUM` 后 SHA-256 仍不同；逻辑 dump 已稳定 | 可考虑提交规范化后的 `catalog.json` 作为权威投影，或接受二进制 churn 并在 CI 中只比较逻辑 dump | #7 |
| 中 | `Last Return` / `Last Return（原 No Return）` 仍为 `CANDIDATE` | `config/work_aliases.json` | 需要独立一手证据才能批准 | #4 |
| 中 | Review Queue 无 CSV 导出；无跨实体双向导航 | `site/review.html` 无导出按钮 | M5 增强 | #8 |
| 低 | 无全设备视觉验收与无障碍 E2E | 无移动端截图证据 | 增加移动端/键盘可达性测试并归档截图 | #8 |
| 低 | `.github/workflows/pages.yml` 的重试/失败恢复策略未实测 | 仅静态阅读 | 合并后观察真实 job 结果 | #7 |

---

## 9. Next Iteration Suggestions（按收益/风险排序）

1. **M2：完成 11 个已审入口仓库的完整代码级审计**（最高收益、最低风险——只需只读阅读，不需要运行第三方代码）。产出机读 `data/research/audits/*.json` + 人读 `docs/audits/*.md`，含固定 commit SHA、入口、技术栈、外部请求、构建条件、许可证、镜像关系、风险分级。
2. **M1：把 907 条原帖量化成可执行审核批次**。建议按 `kind_signal` + `match_status` 分层，`UNRESOLVED` 优先；提供只生成工单（不落库）的脚本，含每批 CSV 与验收标准。
3. **M5：移动端 + 键盘可达性 E2E 与截图归档**。现有 `tests/test_site_e2e.py` 已具备 Playwright 骨架，可直接扩展为多视口 + `tab`/`Enter`/`Escape` 断言；产出截图哈希。
4. **M4：引入 `SourceAdapter` 抽象 + 仅元数据的自动 PR 提案**。同时把 `data/sources.json` 中尚未接入的来源纳入只读漂移检查。
5. **M3（需人工确认）：在隔离容器中实测第三方游戏**。建议先只做 11 个已审入口中的一个，端到端验证"入口 SHA + 环境 + 截图 + 行为断言"闭环，再扩大。
6. **复核本轮 3 个 P1 修复的实现细节**：特别是 `db.py` 中 `updated_at` 的 CASE 表达式是否覆盖所有应触发时间戳更新的字段；以及 `export_seed.py` 在"同一 URL 对应多种真实证据类型"时的取舍（当前 dict 保留最后一条）。
7. **决定 SQLite 的二进制 churn 策略**：是否把权威来源改为"逻辑 dump / JSON 投影 + 可复现构建"，还是接受二进制并在 CI 增加逻辑 dump 一致性校验。

---

## 本轮提交

* 分支：`feat/pi-agent-baseline-hardening-20261117`
* PR：https://github.com/1998x-stack/awsome-games/pull/9
* CI：https://github.com/1998x-stack/awsome-games/actions/runs/44042084460 (`Validate catalog` success)
* 详细基线：`docs/LOCAL_BASELINE_2026-11-17.md`
* 里程碑进度：`docs/IMPLEMENTATION_PLAN.md`
* 结构化事实：`data/reports/pi-agent-latest.json`
