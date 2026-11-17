# 本地部署与回归基线 · 2026-11-17

本文件记录**实际执行**的本地部署、测试与测量结果。所有数字都给出计算方法，便于复核。
凡未实际运行的项目，明确写 `NOT_TESTED` / `BLOCKED`，不做推测。

## 1. 执行环境

| 项目 | 值 | 命令 |
|---|---|---|
| 执行日期 (UTC) | 2026-11-17 | `date -u` |
| OS | macOS (Darwin 25.x, Apple Silicon) | `uname -a` |
| 仓库根目录 | `/Users/x/Desktop/codes/awsome-games` | `pwd` |
| 起始 SHA | `ebab78e8f558abb37f7d02ff458c2edef1607801` | `git rev-parse HEAD` |
| 起始 `origin/main` | 同上（工作树干净，0 ahead / 0 behind） | `git rev-list --left-right --count HEAD...origin/main` |
| 工作分支 | `feat/pi-agent-baseline-hardening-20261117` | `git branch --show-current` |
| 系统 Python | 3.9.6（**低于 README 要求的 3.10+**） | `python3 --version` |
| 项目虚拟环境 Python | 3.12.15（`/opt/homebrew/bin/python3.12 -m venv .venv`） | `.venv/bin/python --version` |
| Node.js | v26.13.1 | `node --version` |
| Git | 2.54.0 (Apple Git-157) | `git --version` |
| Docker | 29.9.1，daemon 报告 Ubuntu 24.04.4 LTS | `docker info` |
| SQLite | 3.54.0 | `python3 -c "import sqlite3..."` |
| Playwright | 1.65.2 + Chromium headless shell 159.0.8154.6 | `.venv/bin/python -m pip list` |
| 可用磁盘 | 658 GB | `df -h .` |

安装的开发依赖（仅本项目需要，未触碰第三方游戏依赖）：

```
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt   # requests, beautifulsoup4
.venv/bin/python -m pip install playwright            # 供 scripts/browser_*.py 使用
.venv/bin/python -m playwright install chromium
```

## 2. 保护现状

* 起始工作树**干净**，`HEAD == origin/main`，无 stash，无他人未推送提交。
* 原 `data/catalog.sqlite` 已备份到 `/tmp/awsome-games-backup/catalog.sqlite.baseline-ebab78e`
  （SHA-256 `602a2a80a77b0e95b883eb419006a8017ee4cca5d857a31c4a0712802b56d5fa`），
  与起始工作树文件逐字节一致。
* 直接使用系统 Python 3.9 会低于项目要求，因此**没有**改动机器上其它 Python 环境。

## 3. 基线指标（真实测得，非 README 复制）

计算命令：`python3 scripts/build_catalog.py --check` + `python3 scripts/check_catalog.py`。

### 3.1 传统目录层（`projects` 等表）

| 指标 | 值 | 来源 / 方法 |
|---|---:|---|
| 作品记录 `projects` | 155 | `SELECT COUNT(*) FROM projects` |
| 去重仓库 `repositories` | 54 | `SELECT COUNT(*) FROM repositories` |
| 作品—仓库映射 | 150 | `SELECT COUNT(*) FROM project_repositories` |
| 有仓库链接的作品 | 150 | `summary.projects_with_repository` |
| 有演示链接的作品 | 59 | `summary.projects_with_demo` |
| 已发现本地 HTML 入口 | 0 | `summary.projects_with_html_entrypoints` |
| 通过 smoke test 的作品 | 0 | `summary.projects_smoke_test_passed` |
| 模型分布 | 5.2: 145 / 5.1: 10 | `summary.by_model` |
| `project_evidence` 行数 | 155 | `SELECT COUNT(*) FROM project_evidence` |
| 已授权发布仓库 | 0 | `config/publication_approvals.json` → `approved_repositories: []` |
| 实际发布到站点的游戏 | 0 | `build_site.py` → `published_games: 0` |

### 3.2 研究层（`research_*` 表）

| 指标 | 值 | 方法 |
|---|---:|---|
| 来源记录 `research_source_records` | 1118 | `SELECT COUNT(*)` |
| 原帖实体线索 `research_posts` | 907 | `SELECT COUNT(*)`；其中 906 个精确 X status ID + 1 条 `orphan:` |
| 作品工程映射 `research_works` | 64 | `SELECT COUNT(*)` |
| 候选 GitHub 仓库 `research_repositories` | 83 | `SELECT COUNT(*)` |
| 归属冲突/反证 `research_claims` | 12 | `SELECT COUNT(*)` |
| 旧库→研究映射 `research_project_links` | 63 | `SELECT COUNT(*)`，全部 `method='EXACT_REPO_AND_TITLE'` |
| 人工作品审核 `research_work_reviews` | 0 | 审核清单 `config/research_reviews.json` 为空 |
| 人工原帖审核 `research_post_reviews` | 0 | 同上 |
| 浏览器运行证据 `research_runtime_evidence` | 0 | **没有任何第三方游戏被验证** |
| 已审静态入口（文件树级） | 11 | `entry_status='TREE_PATH_REVIEWED_NOT_EXECUTED'` |

### 3.3 关于"帖子数量 ≠ 游戏数量"

907 条原帖实体线索、1118 条来源记录、83 个候选仓库、64 个工程映射是**四种不同粒度**。
数据库中尚不存在任何"已验证作品"的升级：`export_projection()` 对每个 work 都输出
`execution_verified: false`。

## 4. 重要发现：已提交的 SQLite 快照不完整

**发现：** 仓库中提交的 `data/catalog.sqlite`（78 页 / 319,488 字节）**只有传统目录层**，
`research_*` 表在首次运行 `build_catalog.py` 时才由 `data/research/v1/*.json` 创建并填充。

验证：

```bash
sqlite3 /tmp/awsome-games-backup/catalog.sqlite.baseline-ebab78e ".tables"
# aliases catalog_view categories evidence_sources ingest_errors ingest_runs
# links project_categories project_evidence project_repositories projects
# prompts repositories repository_files      ← 没有任何 research_* 表
```

首次构建后数据库为 1.37 MB（334 页）。这是**正常且可复现**的：研究层完全由受控的冻结
JSON 快照推导。但它意味着"直接读取仓库里的 `.sqlite`"得到的不是完整研究库。

**残留限制（未修复，如实记录）：** SQLite 二进制文件**不是逐字节可复现的**（页分配/WAL 残留），
即使逻辑内容完全相同。经 `PRAGMA journal_mode=DELETE` + `VACUUM` 后仍不一致。
因此每次本地重建都会让 `data/catalog.sqlite` 在 `git status` 中显示已修改。

## 5. 测试与质量门禁（全部实际执行）

| 命令 | 结果 |
|---|---|
| `python -m unittest discover -s tests -v` | **76 passed, 0 failed**（起始为 56） |
| `python scripts/build_catalog.py --check` | exit 0；integrity_check=ok；foreign_key_errors=0；projects=155 |
| `python scripts/check_catalog.py` | exit 0；`problems: []` |
| `python -m compileall -q scripts tests` | exit 0 |
| `python scripts/build_site.py` | exit 0；`{"projects":155,"repos":54,"published_games":0,"site_bytes":1530556}` |
| `node --check site/assets/{app,research,review}.js` | 全部 exit 0 |
| `bash -n scripts/*.sh scripts/isolation/*.sh bootstrap.sh` | exit 0 |
| `python scripts/review_evidence.py`（dry-run） | exit 0；`{"review_entries":0,"written":0}` |

### 5.1 浏览器端到端（真实 Chromium，非 mock）

用 Playwright + 本地 HTTP 服务遍历三个页面，记录 `pageerror` / `console` / 外部阻断请求：

* `index.html`、`research.html`、`review.html`：**0 page error、0 console error、0 被阻断的外部请求**。
* 交互验证：搜索、模型/类型/分类/源码状态筛选、空结果提示、加载更多（36 → 72 张卡片）、
  详情对话框（`?work=`、`?kind=repositories&id=` 深链）、`Escape` 关闭、CSV 导出下载。
* 统计卡片显示 155 / 54 / 59 / 0，与研究层 1,118 / 907 / 64 / 83 / 12 分开呈现。

这些验证已固化为可重复测试：`tests/test_site_e2e.py`（Playwright 不可用时自动 skip）
与 `tests/test_site_link_policy.py`。

### 5.2 M3 隔离执行器（真实容器，非模拟）

`scripts/isolation/Dockerfile.smoke` + `scripts/isolation/run_isolated_smoke.sh`
在 `--network none --read-only --cap-drop ALL --security-opt no-new-privileges
--pids-limit 256 --memory 1g --cpus 1 --user 65534:65534` 下运行，被审目录**只读挂载**。

| 项目 | 结果 |
|---|---|
| 被测对象 | **本仓库自编写的无害 fixture**（`.cache/isolated-stage/demos/fps/index.html`） |
| 入口 SHA-256 | `5af5f546bb8bd5090e70747d15a82e8817af0a6ddf06608f136331d2ba7cac87` |
| `status` | `BROWSER_LOAD_CHECKED` |
| `iframe_isolation` | `true` |
| `frame_body_loaded` | `true` |
| console errors / blocked requests / failed requests / http errors | 空 |
| `gameplay_verified` | `false`（脚本从不自称可玩） |
| 截图 | `.cache/iso-reports/smoke.png`（SHA-256 `5a91a8c388c78289ebae06c5746de054d3e043eb760ffaf02199706a234345c0`） |
| **第三方游戏** | **`NOT_TESTED`（0 个）** |

另有 `--network none` 下的自编 fixture 交互探针：`gameplay_interaction: PASS`、
`parent_document_access: BLOCKED`、`third_party_games_verified: 0`。

**阻断证据（fail-closed 验证）：** 用自编 fixture 冒充真实 `work_id=F52-W012` 导入报告时，
`import_browser_report.py` 以 `Missing/unsafe staged entry` 拒绝（因为入口必须与
`research_works.entry_path` 的已审入口一致），`research_runtime_evidence` 保持 0 行。

## 6. 本轮修复的真实缺陷（均有回归测试）

| # | 严重度 | 缺陷（实测证据） | 修复 |
|---|---|---|---|
| 1 | P1 | `review.html` 的"关联研究记录"跨页链接被渲染成不可点击的 `<span>`：`safeUrl()` 用 `new URL(value)` 解析相对地址会抛异常。M5 要求的 `Post ↔ Work ↔ Repository ↔ Audit` 溯源跳转实际不可用（实测 `footer.locator("a").count() == 1`） | 三个前端统一改为 `new URL(value, document.baseURI)`，同源目标保持相对路径（兼容 GitHub 项目 Pages 的 `/<repo>/` 子路径），并补上凭据拒绝 |
| 1b | P1 | **链接可点后仍不可用（线上发现）**：`makeLink()` 对**所有**链接强制 `target="_blank"`，点击后在**新标签页**打开而不是就地导航（线上实测 `target=_blank`，新标签 URL = `.../research.html?kind=repositories&id=...`） | 仅**跨源**链接开新标签页；同源溯源跳转就地导航。测试改为真实 `click()`（PR #10） |
| 2 | P1 | 幂等导入实际**不幂等**：`AUTOINCREMENT` + 冲突的 `INSERT OR IGNORE` 每次运行都推进 `sqlite_sequence`；`projects.updated_at` 无条件改写为当前时间。两次 `build_catalog.py --check` 的逻辑 dump 相差 10 行 | AUTOINCREMENT 表改为 `INSERT ... SELECT ... WHERE NOT EXISTS` 守卫式插入；`updated_at` 改为仅在内容真正变化时才推进。修复后两次运行 dump 差异 = **0 行** |
| 3 | P1 | `export_seed.py` 把每条作品的证据类型硬编码为 `sqlite_snapshot_reconstruction`，重新导入时与真实证据行并存 → `project_evidence` 由 155 **翻倍到 310**，`site/data/catalog.json` 为全部 155 个作品公开了一个伪造来源 | 导出保留每来源真实 `evidence_type`/`confidence`（`evidence_by_source`）；`seed_database` 优先使用它，且**永不**把 `SYNTHETIC_EVIDENCE_TYPES` 标记落成证据行。重新生成 `data/seeds/legacy_projects.jsonl` 后 `project_evidence` 稳定在 155，投影中占位符为 0 |
| 4 | P2 | `build_catalog.py --fresh` 直接 `unlink()` 权威 SQLite，无任何可恢复副本 | 删库前用 SQLite backup API 写入 `data/backups/catalog-<UTC>.sqlite` 并做 `integrity_check`，失败则拒绝重建 |
| 5 | P2 | `site/index.html` 硬编码"83 个仓库"等统计数字，会与真实数据漂移 | 改为不含量值的文案，并加测试禁止静态页面硬编码研究统计 |
| 6 | P2 | `app.js` / `research.js` 的 URL 白名单未拒绝带内嵌凭据的 `https://user:pass@…` | 三个前端统一拒绝 username/password |
| 7 | P2 | `.gitignore` 未忽略 `.venv/`，而 README 要求创建 `.venv` | 补上 `.venv/`、`venv/` |

## 7. 未完成 / 阻塞

| 项目 | 状态 | 原因 |
|---|---|---|
| 第三方游戏 Chromium 实测 | `NOT_TESTED` | 未克隆任何第三方源码（`games/_repos` 不存在）；运行第三方程序属"第三方执行"，需人工确认。隔离能力已就绪 |
| 11 个已审静态入口的真实运行 | `BLOCKED` | 同上；且入口文件不在本地 |
| 83 个候选仓库的逐行源码/许可证审查 | `NOT_STARTED` | 只有 GitHub 文件树与部分 README 级核验 |
| 904 条未归并原帖的逐条证据审核 | `NOT_STARTED` | 需要一手证据；不得自动升级为作品 |
| GitHub Pages 生产发布核实 | **`VERIFIED`** | 两个 PR 合并后 `build` 与 `deploy` 两个 job 均 success；线上页面全部 HTTP 200；真实 Chromium 点击验证通过（详见 HANDOFF 第 7 节） |
| SQLite 逐字节可复现 | `NOT_STARTED` | 逻辑内容已稳定；二进制层面未解决（第 4 节） |

## 8. 测试质量教训

PR #9 的 E2E 测试用 `page.goto(href)` **直接跟随**链接，没有真正点击，因此没能发现 `target="_blank"` 缺陷——该缺陷只在**对线上部署真实点击**时才暴露。已修正：

* 导航类测试一律使用真实用户手势（`click()`），不得用直接导航代替。
* 新增源码契约 `test_internal_links_do_not_force_a_new_tab`，禁止无条件的 `a.target='_blank'`。
* 两个新测试已在**修复前**的提交版本上验证会失败（`AssertionError: '_blank' is not None`），修复后通过。

## 9. 复现本基线

```bash
git checkout main && git pull            # 已包含 PR #9 与 PR #10
/opt/homebrew/bin/python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/build_catalog.py --check
.venv/bin/python scripts/check_catalog.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/build_site.py
node --check site/assets/app.js && node --check site/assets/research.js && node --check site/assets/review.js
bash -n scripts/*.sh scripts/isolation/*.sh bootstrap.sh
# 隔离执行器（可选，需要 Docker）
docker build -f scripts/isolation/Dockerfile.smoke -t awsome-games-smoke .
bash scripts/isolation/run_isolated_smoke.sh --root .cache/isolated-stage \
  --entry demos/fps/index.html --out .cache/iso-reports
```
