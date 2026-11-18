# PI Agent 交接报告 · 2026-11-17 → 2026-11-18

> **最新一轮见文末 `## 10.`（2026-11-18 全量实测）**；第 1–9 节为 2026-11-17 批次，保留原文以便对照。

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
| PR | https://github.com/1998x-stack/awsome-games/pull/9 （已合并）· https://github.com/1998x-stack/awsome-games/pull/10 （已合并） |
| CI | #9: https://github.com/1998x-stack/awsome-games/actions/runs/44042084460 · #10: https://github.com/1998x-stack/awsome-games/actions/runs/44043909660 — 均 `Validate catalog` = **success** |
| main 结束 SHA | `3375af2af1f8c68658d606b709326df7f439bfcb` |
| 生产 Pages | 已部署并**真实点击验证**（见第 7 节） |

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
| 单元测试数 | 56 | **76** | `python -m unittest discover -s tests -v` | +20 个回归测试 |

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
| `site/assets/review.js`、`research.js` | **修复后续缺陷（#10）**：`makeLink()`/`link()` 对所有链接强制 `target="_blank"`，导致应用内溯源跳转离开当前标签页。现仅跨源链接开新标签页 | `VERIFIED`（线上真实点击） |
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
| `gh pr create ...` | PR #9、PR #10 |
| `gh pr checks 9` / `gh pr checks` | `validate  pass  13–14s` |
| `gh pr merge 9 --squash --delete-branch` | MERGED，merge commit `e41b877c542bb139ca942782fc93a09328c4dbd2` |
| `gh pr merge 10 --squash` | MERGED，merge commit `3375af2af1f8c68658d606b709326df7f439bfcb` |
| `gh run view <pages run> --json jobs` | `build -> success`、`deploy -> success` |
| `curl` 线上页面与数据文件 | 全部 HTTP 200（见第 5 节） |
| Playwright 真实点击线上链接 | 0 个新标签页，就地导航，详情对话框打开 |

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

### 生产站点实测（2026-11-17，合并并部署之后）

对 `https://1998x-stack.github.io/awsome-games/`（注意：Pages **项目站点**位于 `/<repo>/` 子路径，正是修复所针对的场景）执行真实 Chromium 验证：

| 检查 | 结果 |
|---|---|
| 三个页面 page error | 0 |
| 外部证据链接 `target` | `_blank` |
| 内部 Evidence Lab 链接 `target` | **无**（就地导航） |
| 点击内部链接后新开标签页数 | **0** |
| 导航后的 URL | `.../awsome-games/research.html?kind=repositories&id=0xCodez%2Fthousand-peaks` |
| 详情对话框 | 已打开，标题 `Dragon of a Thousand Peaks` |
| 线上统计（研究层） | 1,118 / 907 / 64 / 83 / 12 |
| 线上统计（目录） | 155 / 54 / 59 / 0 |
| 线上 `build-manifest.json` | `repository_ref = 3375af2af1f8c68658d606b709326df7f439bfcb`、`playable_published = 0`、`repository_snapshots_published = []` |
| 线上资源 HTTP 状态 | 全部 200 |

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
| commit #9 | `fix(M1/M3/M5): restore provenance fidelity, idempotent rebuild and cross-page evidence links` |
| commit #10 | `fix(M5): keep the Evidence Lab audit-trail link in the same tab` |
| 分支 | `feat/pi-agent-baseline-hardening-20261117`、`fix/m5-internal-evidence-link` |
| 推送 | 成功，**未强推** |
| PR #9 | https://github.com/1998x-stack/awsome-games/pull/9 — MERGED (`e41b877c542bb139ca942782fc93a09328c4dbd2`) |
| PR #10 | https://github.com/1998x-stack/awsome-games/pull/10 — MERGED (`3375af2af1f8c68658d606b709326df7f439bfcb`) |
| CI (#9) | `Validate catalog` = **success**（14 s）· https://github.com/1998x-stack/awsome-games/actions/runs/44042084460 |
| CI (#10) | `Validate catalog` = **success**（13 s）· https://github.com/1998x-stack/awsome-games/actions/runs/44043909660 |
| 分支保护 | `main` **未受保护**（`GET /branches/main/protection` → 404），无需人工审批 |
| GitHub Pages workflow (#9) | https://github.com/1998x-stack/awsome-games/actions/runs/44042834054 — `build` success、`deploy` success |
| GitHub Pages workflow (#10) | https://github.com/1998x-stack/awsome-games/actions/runs/44044106186 — `build` success、`deploy` success |
| Pages URL | https://1998x-stack.github.io/awsome-games/ |
| deployments | #9 → id 7847475003 (`e41b877c…`) · #10 → SHA `3375af2a…` |

### 生产上线核实（真实证据，非推测）

```
curl -s -o /dev/null -w '%{http_code}' https://1998x-stack.github.io/awsome-games/
/           200   /research.html 200   /review.html 200
/assets/review.js 200   /data/review-queue.json 200   /data/research.json 200
/data/catalog.json 200  /build-manifest.json 200

# 线上产物确实来自本次合并提交：
build-manifest.json -> repository_ref = 3375af2af1f8c68658d606b709326df7f439bfcb
                       playable_published = 0
                       repository_snapshots_published = []
                       preview_unapproved = false

# 线上真实 Chromium 点击验证：
external target = _blank   |   internal target = None
tabs opened after clicking internal link = 0        → 就地导航
url = .../awsome-games/research.html?kind=repositories&id=0xCodez%2Fthousand-peaks
detail dialog open = True  |  detail title = "Dragon of a Thousand Peaks"
page errors = []（三个页面均为 0）
live research stats = 1,118 / 907 / 64 / 83 / 12   |   live index stats = 155 / 54 / 59 / 0
```

**未发布任何第三方源码**：`repository_snapshots_published: []`、`playable_published: 0`。

> **测试质量教训（已修正）**：PR #9 的 E2E 测试用 `page.goto(href)` 直接跟随链接，**没有真正点击**，因此没能发现 `target="_blank"` 的缺陷。该缺陷是在对**线上部署真实点击**时才暴露的。PR #10 已把测试改为真实 `click()`，并新增“内部链接不得强制开新标签页”的源码契约；两个测试在合并前的旧代码上均**先失败**（`AssertionError: '_blank' is not None`），修复后通过。教训：溯源类测试必须用真实用户手势，不能用直接导航代替。

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
| 低 | 溯源类 E2E 曾用 `page.goto()` 代替真实用户手势，导致漏检 `target="_blank"` | PR #9 的测试 vs PR #10 的修正 | 已修复（#10 改为真实 `click()`）；后续所有导航类测试一律用真实手势 | #8 |

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

---

## 10. 2026-11-18 全量隔离实测轮次

分支 `feat/deep-build-all-repos`，起点 `0f6ed51`。本轮目标：**把本地已解析出的每一个入口都真正在隔离容器里跑一遍**，
并让结论可复现、可审计。要求使用 subagents 并行。

### 10.1 结论摘要（含一次自我更正）

| 指标 | 值 |
|---|---|
| 已克隆到本地的仓库 | 54（3.4 GB，均在 `.gitignore` 之外，不入库） |
| 有可测入口的仓库 | 32 |
| **实测入口** | **123 / 123（0 未测）** |
| 加载干净（`BROWSER_LOAD_CHECKED`） | 74 |
| **可归因于输入响应（`INPUT_RESPONSIVE`）** | **4** |
| 页面自行重绘、输入响应无法分离 | 15 |
| 明确失败（见 10.8 分类） | 26 |
| 阻塞驱动、被硬终止（120 秒下依旧可复现） | 3 |
| `GAMEPLAY_VERIFIED` | **0（刻意）** |

**必须先说清一次更正**：本轮中途我一度把 `INPUT_RESPONSIVE` 报成 **11 条**，
上一轮则报过 **4 条**。两次都不对。

11 条里 **10 条在空闲基线期间像素就已经在变**，其中 **7 条从加载到结束 DOM 字节完全相同**——
canvas 动画无论有没有注入输入都会改变像素，那种差异什么也证明不了。
按修正后的归因规则重判，真正可归因的只有 **4 条**；上一轮报的 4 条里也有 2 条（`the-boondocks-the-woodcrest-files`、`emberdeep`）
不满足该规则。规则实现在 `scripts/input_attribution.py`，**探针与离线汇总器共用**，
所以历史报告是用修正规则重判的，而不是重跑浏览器（重跑会换掉证据）。

### 10.2 一个诊断：停顿 4–17 分钟的真正原因

```bash
docker info --format 'CPUs={{.NCPU}} Mem={{.MemTotal}}'
# CPUs=2  Mem=4095643648
```

Docker Desktop 只分给 VM **2 个 CPU / 4 GB**，而容器请求 `--cpus 2`（即整台 VM）。
我为了看进度而临时起容器、或跑 `docker exec`，都会与正在渲染的 Chromium 抢同一批周期，
单条耗时从 3.5 秒涨到分钟级。**是轮询拖慢了整批，不是被测页面。**
这条纪律写进了 `docs/BROWSER_SMOKE.md`：**进度看容器 stdout，不要为看进度再起容器**。
（同一现象再次复现：一次带每 15 秒轮询的 2 条小测试用了 180 秒才退容器，不轮询的同一测试 30 秒就退出。）

### 10.3 harness 的 4 个真实缺陷，其中 1 个是我自己的回归

| 缺陷 | 后果 | 处理 |
|---|---|---|
| `--collect` 被前置的 `--root` 校验拦住 | 报告取不回来 | 调整校验顺序 |
| `--detach` 仍带 `--rm` | 容器退出即被删，`docker cp` 无对象 | 分离模式剔除 `--rm` |
| 镜像 `ENTRYPOINT` 是 `python3` | shell 脚本被喂给 Python（SyntaxError） | 批处理覆盖 entrypoint |
| 清单落在共享路径 | 并行分片互相覆盖清单 | 按 `--name` 分域 |

**第 5 个是我引入的回归，由 subagent 如实报出**：我另写了一个 shell 驱动 `batch_loop.sh` 替换既有的
Python 驱动，理由（"Python 杀不掉阻塞的 Python"）是**错的**——既有 `run_batch` 早就把监督权交给外部
`timeout -s KILL`，并做了 `start_new_session` + `killpg`、子进程输出重定向到文件、超时写 `TIMEOUT_ABORTED`。
我的替代版本在兜底调用里漏传了必填的 `--root`，又把 stderr 丢进 `/dev/null`，于是
**5 条超时报告被静默吞掉**（109/114）。子代理通过"报告数 ≠ 清单数"发现并指出。
处理：**删掉我的驱动，复用既有实现**（更少的代码、没有回归），并补上真正需要的能力
（`--detach` / `--collect` / 按名分域清单）。随后**用故意阻塞的 fixture 实测了超时路径**——
这正是一开始就该做的验证，也正是它缺席才让 bug 藏住。

### 10.4 另外两处诚实性修正

* **`gameplay_verified` 与 `input_responsive` 语义分家。** 汇总器原先把"探针对合成输入有反应"直接计入
  `gameplay_verified`；而 `import_browser_report.py` 强制自报报告必须写 `gameplay_verified: False`，
  两处同名不同义。现在探针一律写 `False`，汇总产物 `counts.gameplay_verified` **恒为 0**（有回归测试守住），
  机器能做出的最强主张是 `counts.input_responsive`。
* **分类器漏掉一整类沙箱不兼容。** `circular-tic-tac-toe` 落在 `OTHER`，原因是
  `Failed to read the 'serviceWorker' property ... lacks the 'allow-same-origin' flag`——
  与 `shooter.html` 的 `localStorage` **同一根因**。已并入 `SANDBOX_OPAQUE_ORIGIN_BREAKS_OWN_SCRIPT`
  （该类别涵盖"页面自身使用同源限定 API"）。同时把 `Page crashed` / `Target crashed` 从
  `DRIVER_FLAKE_OR_TIMEOUT` 拆出为 `RENDERER_CRASHED_ENVIRONMENT_LIMIT`——在本机 2 CPU / 4 GB 上，
  渲染器崩溃是**环境上限**，不是产物属性。

### 10.5 `needs_review` 19 → 0

* **11 个入口路径**用页面 `<title>` 与目录标题**逐字对得上**才写入 `config/project_overrides.json`
  （例：`XDracam/spaceappschallenge2026/game/index.html` 的 title 就是 `T-Minus`；
  `ONE_PROMPT_WORLDS` 的 13 个游戏按其标题精确映射到 `gameN/`，注意其根 `index.html` 只是菜单）。
* **7 个根本不是浏览器作品**：Unity（`Assets/`+`Builds/`+`PLAY.bat`）、Godot（`project.godot`）、
  Rust（`Cargo.toml`）、C + `Makefile`。这些仓库**没有任何 HTML**，留在 `needs_review` 等于假装问题未查清。
  新增声明式状态 `not_browser_based`，每条必须带 `note` 说明证据。
* **1 个是打包器外壳**：`t-minus` 引用 `%BASE_URL%` 与 `/src/main.tsx`，按证据改判 `requires_build`
  （没有为了"多测一个"把它当静态入口）。
* 声明式状态**只允许** `DECLARED_REVIEWED_STATUSES` 中的值，且**不能声明运行时结果**——有回归测试守住。
* 顺带修掉一个真实误判：`aaron-sulbaran/jester` 曾因**缺三个 favicon** 被判 `missing_assets`。
  运行时探针本就把图标/字体 stub 成空响应，两侧标准已对齐；实测真实原因是它自身的 TS module
  在必需沙箱下被 CORS 拒绝（`SANDBOX_OPAQUE_ORIGIN_BREAKS_OWN_SCRIPT`）。
  同一规则下 `bhoult/phone-games` 缺的 `engine.js`（功能性依赖）仍被正确报出。

### 10.6 新增：把实测结论写进权威库的写入者

在此之前，库里的 `sandbox_incompatible` / `runtime_*` 行**没有任何脚本能产生**，
只有 `collect_repositories.py` 的 `RUNTIME_REVIEWED_STATUSES` 在"保留"它们。
一个任何脚本都产生不了的结论是不可审计的，所以补上 `scripts/apply_survey_to_catalog.py`，按构造 fail-closed：

* 只写限制性状态，**没有任何路径能让作品因此变可发布**；
* 拒跑不合格证据文件（缺 `captured_at`、缺隔离配置、**作出结论的条目缺指纹**）；手写一份"普查"改不动库；
* `PAGE_BLOCKED_DRIVER` 是特例：它的证据恰恰是"没有指纹"，因此改为要求必须记录硬超时原因；
* **绝不弱化既有结论**；
* 补上了**基于证据的撤回**：一份同样有证据的 PASS 可以把陈旧的限制性状态撤回到入口态
  （缺 `iframe_fingerprint`/未确认 iframe 隔离的 PASS 不允许撤回）；
* 每行记下证据文件 sha256。

干跑已暴露一个**需要人工判断的真冲突**：`ironvale` 库里是上一轮实测的 `runtime_no_interaction`
（"测过，无反应"），而本轮重测结果是 `runtime_driver_timeout`（"这次测不出来"）。
守卫**拒绝**用"测不出来"抹掉"已经测过"，并把冲突打印出来——保留已测量的结论，交由人工判断。

### 10.7 全量结果（123 个入口）

```
78  PASS                                            (74 BROWSER_LOAD_CHECKED + 4 INPUT_RESPONSIVE)
15  INPUT_RESPONSE_NOT_ATTRIBUTABLE                   页面持续自行重绘，输入响应无法分离
10  EXTERNAL_CDN_REQUIRED                             依赖外部 CDN 上的真实 JS（依赖分类，非缺陷）
 9  SANDBOX_OPAQUE_ORIGIN_BREAKS_OWN_SCRIPT           必需沙箱给帧不透明源：自身 ES module 被判 CORS，
                                                     或读取 localStorage / serviceWorker 时抛错
 3  PAGE_BLOCKED_DRIVER                               阻塞驱动，外部 timeout -s KILL 终止（60 与 120 秒均复现）
 2  OPTIONAL_DEVICE_SENSOR_DENIED                     accelerometer / fullscreen 策略拒绝
 3  DRIVER_FLAKE_OR_TIMEOUT                           iframe 可见但 bounding_box/可见性定位超时等驱动侧问题
 1  RENDERER_CRASHED_ENVIRONMENT_LIMIT                渲染器崩溃（本机 2 CPU / 4 GB 的环境上限，2 GB 内存下复现）
 1  THIRD_PARTY_ANALYTICS_BLOCKED                     加载第三方分析脚本
 1  NO_OBSERVABLE_RESPONSE                            能加载，输入后无任何可观测变化
```

**关于 `SANDBOX_OPAQUE_ORIGIN_BREAKS_OWN_SCRIPT`（9 条）必须加上限定**：这不是"这 9 个游戏是坏的"。
它说的是"在我们**必需**的沙箱下（刻意不给 `allow-same-origin`）帧成为不透明源，
页面自身的 ES module 因此被判 CORS 失败"。在普通 HTTP 源下它们很可能正常。
把这类产物变可玩只有一条路——**放宽沙箱**，而那是本项目明确不做的事（见 `AGENTS.md`）。
所以这是"与我们安全要求的兼容性"结论，不是产物缺陷结论；它们不会被发布。

**4 条可归因输入响应的原始证据**（加载干净、0 控制台错误、0 阻断请求、iframe 隔离为真）：

| 条目 | 仓库 | 归因依据 |
|---|---|---|
| `soccer-time-dev-5-1` | Time-dev-alt/Fable-5.1-Games | DOM 在空闲期字节不变，注入输入后变化 |
| `neon-runner` | Ilias-AK/NewGameFromFable5.2 | 同上 |
| `sternenjager` | oldzitterhand/sternenjaeger | 同上 |
| `world-1-1` | sorrycc/fable-arcade | 像素在空闲期稳定，注入输入后变化（DOM 未变） |

**线上可玩数不变，仍为 1**：只有 `Time-dev-alt/Fable-5.1-Games/Soccer.html` 同时满足
"仓库在发布白名单内 + 许可证已核对"。**新增的 3 个可归因作品不会自动上线**——
本 agent 不修改 `config/publication_approvals.json`。

### 10.8 验证证据

```
数据一致性   check_catalog.py                          problems: []                    PASS
             build_catalog.py --check                  integrity ok / FK 0             PASS
单测         test_hardening + test_catalog             52 passed                       PASS
             test_isolation_harness                    37 passed                       PASS
静态         compileall / bash -n / node --check       ok                              PASS
容器自测     故意阻塞 fixture + 正常 fixture            TIMEOUT_ABORTED + LOAD_CHECKED  PASS
             （修复前该路径静默丢失报告，修复后 14/14 齐全；重试批 8/8 齐全）
```

本轮新增回归测试：声明式状态与离线重分类 6、装饰性资源 4、输入归因 9、分类覆盖 5、
应用器（含撤回与证据规则）8。

### 10.9 仍然没有做到的（不粉饰）

* **7 个入口在本机环境内测不出结论**（3 个阻塞驱动、3 个驱动侧定位超时、1 个渲染器崩溃）。
  它们**没有**被写成对产物的判断：只记 `runtime_driver_timeout` 或不记状态。重试结果见 10.10。
* **仍然没有 `GAMEPLAY_VERIFIED`**，且这是刻意的：机器能做出的最强主张只是可归因的输入响应。
* **仍未实现逐游戏的行为断言**（点击 X 应导致状态 Y）。
* **10 个 `missing_assets` / 9 个 `requires_build`** 在静态条件下确实跑不了（缺功能性资源或需构建），
  这不是待办积压，而是结论。
* **32 个研究候选仓库**仍未做 M2 代码级审计后才克隆——这是刻意的隔离，不是遗漏。
* **5 个只有外链演示的作品**（CROSSTOWN、Oil Paint、Starry Nightrider、Tennis、What the Water Keeps）
  没有仓库，需要另做"真实 URL 测试器"，本轮未做。
* `data/reports/repo-survey-2026-11-17.json` **按原文保留**（当时的结论是当时的证据），
  但其中的 `gameplay_verified: 3` 用的是已被证明错误的归因规则；新文件
  `data/reports/repo-survey-2026-11-18.json` 为修正后的版本，`gameplay_verified` 恒为 0。

### 10.10 对未能测出的 8 个入口各重试一次（结果：只转换了 1 个）

配置：`--memory 2g`、`--per-entry-timeout 120`（原为 1 GB / 60 秒）。TOTAL：
`BROWSER_LOAD_CHECKED 1 | INCOMPLETE_OR_FAILED 4 | TIMEOUT_ABORTED 3`，8/8 报告齐全。

| 条目 | 原结果 | 重试结果 | 结论 |
|---|---|---|---|
| `aurora-over-the-fjord` | `TIMEOUT_ABORTED` | **`BROWSER_LOAD_CHECKED`** | **唯一转换**：它只是慢/重，60 秒不够，不是坏的 |
| `emberdeep` | `TIMEOUT_ABORTED` | `TIMEOUT_ABORTED` | 阻塞可复现，**日志 0 字节**（子进程完全无输出） |
| `ironvale` | `TIMEOUT_ABORTED` | `TIMEOUT_ABORTED` | 同上；且库里保留上一轮实测的 `runtime_no_interaction`（见 10.6 的冲突） |
| `mothlight-vesper-9` | `TIMEOUT_ABORTED` | `TIMEOUT_ABORTED` | 同上 |
| `lichen-on-slate` | `DRIVER_FLAKE` | `INCOMPLETE_OR_FAILED` | `Locator.wait_for: Timeout 30000ms` 等 iframe 可见，iframe 始终不可见 |
| `misremember` | `DRIVER_FLAKE`（崩溃） | `INCOMPLETE_OR_FAILED`（仍 `Page crashed`） | 2 GB 下仍崩溃 → 不是 1 GB 的问题，是本机渲染环境上限 |
| `saltline` | `DRIVER_FLAKE`（崩溃） | `INCOMPLETE_OR_FAILED` | iframe **可见**，但 `bounding_box` 15 秒超时 → 驱动侧限制 |
| `tidebell` | `DRIVER_FLAKE` | `INCOMPLETE_OR_FAILED` | 同 `saltline` |

因此最终"环境/驱动侧阻碍"的条目是 **7 个**（3 阻塞 + 3 定位超时 + 1 崩溃），不是 8 个。
**`--per-entry-timeout` 没有为了凑结果而被下调，超时条目也没有重试到出现不同答案为止**：
第二次得到相同结论本身就是可报告的结果。

被阻塞条目的 `.log` 是空的（0 字节），这点值得记下：对这类条目**唯一存在的证据就是那条硬超时记录**，
因此写入器对它们的证据要求是"必须记录硬超时原因"，而不是"必须有指纹"（见 10.6）。
