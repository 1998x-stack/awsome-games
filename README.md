# awsome-games

**AI 游戏与创意编程作品数据库、GitHub 源码采集器和在线试玩站点。**

本仓库以 Claude Fable 5.1 / 5.2 作品为首批数据，采用 SQLite 管理作品、分类、仓库、入口文件和证据，再通过 GitHub Pages 发布可搜索目录。已采集的静态 HTML 游戏可以在网站内尝试运行。

> 重要：本仓库不声称已经获得互联网上所有作品。当前数据是 2026-11-16 调查快照；作品数量、模型归属和源码关系会随着证据更新而变化。


## Evidence Lab：新增的作品实体与反证层（2026-11-17）

在原有的 **155 条项目 / 54 个去重仓库** 基线之外，新增了一套**不覆盖旧库**的证据研究数据层：

| 新增研究单元 | 数量 | 为什么不能直接相加 |
|---|---:|---|
| 原索引事实性记录 | 1,118 | 同一 X 原帖可能出现在多个索引 |
| 原帖实体线索 | 907 | 906 个原帖 ID + 1 条缺失 ID，尚未逐项确认独立作品 |
| GitHub 候选地址 | 83 | 包含原创、镜像、工具、Pull Request 和非网页项目 |
| 社区作品—仓库映射 | 64 | 仅保守精确关联到现有 155 条项目 |
| 重点归属反证 | 12 | 模型版本冲突、错误仓库归属及多模型协作 |

新增的 **[Evidence Lab 在线研究页](site/research.html)** 支持在四种不同粒度之间检索、查看原始证据、定位静态源码入口/交付形态、提示词信息、外部依赖、人工参与记录并导出 CSV。通过 Pages 构建后浏览 /research.html。人工校正请写入 `config/research_reviews.json`，由 `scripts/review_evidence.py` 校验与保存独立审计历史。

数据快照在 [data/research/v1/](data/research/v1/)，规范与审计报告见 [docs/RESEARCH_INTEGRATION.md](docs/RESEARCH_INTEGRATION.md)，隔离浏览器加载检查见 [docs/BROWSER_SMOKE.md](docs/BROWSER_SMOKE.md)。这些记录不会默认克隆或发布任何未经授权的第三方代码；**已审入口 ≠ 经过浏览器试玩验证**。请先运行以下命令生成站点投影：

    python3 scripts/build_catalog.py --check
    python3 scripts/build_site.py
    python3 -m unittest discover -s tests -v


## 当前首批数据

| 指标 | 数量 | 说明 |
|---|---:|---|
| 作品记录 | **155** | Fable 5.1：10；Fable 5.2：145 |
| 去重 GitHub 仓库 | **54** | 一个仓库只克隆一次 |
| 作品—仓库关系 | **150** | 同一个合集仓库可以对应多款作品 |
| 有仓库链接的作品 | **150** | 仅表示索引中存在公开仓库地址 |
| 有试玩链接的作品 | **59** | 未保证每个链接当前可用 |
| 单文件 HTML 视觉实验 | **76** | 来自 MiaAI-Lab 的作品合集 |
| 已发现本地 HTML 入口 | **0（初始状态）** | 运行采集器后逐步增加；入口发现不等于试玩验证 |

当前数据库已将作品分类为 FPS、动作、平台跳跃、竞速、策略、模拟经营、沙盒开放世界、探索、恐怖、解谜、体育、生存、角色扮演、叙事、街机、3D 世界、互动艺术、生成艺术、视觉实验、动画、网页工具、音乐、数据可视化和视频演示等类别。

## 项目结构

```text
awsome-games/
├── config/
│   ├── categories.json              # 规范化分类词表
│   ├── project_overrides.json       # 手工指定作品 HTML 入口
│   └── repository_overrides.json    # 仓库级采集配置
├── data/
│   ├── catalog.sqlite               # SQLite 关系数据库
│   ├── catalog.json                 # 完整 JSON 导出
│   ├── projects.csv                 # 作品表格
│   ├── repositories.csv             # 去重仓库清单
│   ├── summary.json                 # 统计摘要
│   ├── sources.json                 # 数据来源清单
│   └── seeds/                       # 初始 155 条作品数据
├── docs/                            # Schema、采集器、Pages、安全说明
├── games/_repos/                    # 本地采集的游戏源码快照（运行脚本后生成）
├── scripts/
│   ├── build_catalog.py             # 导入种子、维护 SQLite、导出 JSON/CSV
│   ├── collect_repositories.py      # 核心：克隆仓库、复制网页代码、识别入口
│   ├── build_site.py                # 生成 GitHub Pages 静态站
│   ├── refresh_community_indexes.py # 联网更新社区索引
│   ├── check_catalog.py             # 数据库和文件完整性检查
│   ├── collect_all.sh               # 首次全流程
│   └── refresh_all.sh               # 后续增量更新流程
├── site/                            # Pages 网站模板与静态资源
├── tests/                           # 自动化测试
└── .github/workflows/               # CI 与 Pages 部署
```

## 快速开始

要求：Python 3.10+、Git、可访问 GitHub 的网络。建议 macOS/Linux；Windows 可在 WSL 中运行。

```bash
git clone https://github.com/1998x-stack/awsome-games.git
cd awsome-games

python3 -m venv .venv
source .venv/bin/activate        # Windows WSL 同样适用
python3 -m pip install -r requirements.txt

# 1. 导入 155 条首批作品记录并建立 SQLite
python3 scripts/build_catalog.py

# 2. 先查看待采集仓库
python3 scripts/collect_repositories.py --dry-run

# 3. 建议先采集 2 个仓库试运行
python3 scripts/collect_repositories.py --limit 2

# 4. 确认结果后采集全部唯一仓库
python3 scripts/collect_repositories.py

# 5. 更新导出文件、网站并检查
python3 scripts/build_catalog.py
python3 scripts/build_site.py
python3 scripts/check_catalog.py

# 6. 本地预览
python3 -m http.server 8000 --directory site
```

浏览器访问 `http://localhost:8000`。

### 一条命令执行采集与构建

```bash
bash scripts/collect_all.sh
```

如需更新社区清单，再执行：

```bash
bash scripts/refresh_all.sh
```

## 核心：源码克隆和游戏入口识别

```bash
# 全部 54 个去重仓库，只克隆一次
python3 scripts/collect_repositories.py

# 指定仓库
python3 scripts/collect_repositories.py --repo MiaAI-Lab/Claude-Fable-5.2-HTML-Files

# 强制刷新已有快照
python3 scripts/collect_repositories.py --force

# 调整单文件和单仓库快照容量上限（MB）
python3 scripts/collect_repositories.py --max-file-mb 80 --max-total-mb 800
```

源码会进入 `games/_repos/<owner>__<repo>/`，并在数据库中记录仓库 commit SHA、许可证、文件清单、入口路径和采集状态。`.git`、`node_modules`、缓存、虚拟环境、`.env` 和密钥文件不会复制。**脚本不会运行第三方项目的 npm install、build 或其他执行脚本。**

如果仓库中存在多个 HTML 页面，采集器不会随便挑一个冒充游戏入口。它优先使用人工配置、原始 GitHub 文件链接、作品目录链接、唯一 HTML 文件或明确的标题路径匹配；无法确定时标记为需要复核。

### 手动指定入口

编辑 `config/project_overrides.json`：

```json
{
  "projects": {
    "fab_0123456789abcdef": {
      "entry_path": "public/index.html"
    }
  }
}
```

路径相对于对应 GitHub 仓库根目录。再次运行 `collect_repositories.py` 即可。

## 数据库

主库为 `data/catalog.sqlite`。核心实体包括：

- `projects`：作品
- `categories` / `project_categories`：分类词表与多标签关系
- `repositories` / `project_repositories`：去重仓库及作品—仓库关系
- `repository_files`：HTML/CSS/JS/图片/音频等源码文件清单
- `links`：试玩、作者帖子等链接
- `prompts`：Prompt 状态与来源
- `evidence_sources` / `project_evidence`：证据来源和可信度
- `ingest_runs` / `ingest_errors`：采集运行记录与错误

详细字段、关系和状态语义见 [docs/SCHEMA.md](docs/SCHEMA.md)。

## GitHub Pages：浏览与试玩

仓库包含 `.github/workflows/pages.yml`。在 GitHub 仓库 **Settings → Pages → Build and deployment → Source** 中选择 **GitHub Actions**。推送到 `main` 后，Workflow 会生成目录、复制已采集游戏文件并部署 Pages。

网站支持：

- 作品搜索、模型版本筛选、内容类型筛选、游戏分类筛选；
- 按源码仓库、已采集源码、本站可试玩入口、在线演示筛选；
- 查看仓库、作者帖子和原始演示；
- 对经授权发布且有 HTML 入口的项目点击“尝试试玩”，在隔离 iframe 中运行；
- 导出当前筛选结果 CSV。

`entrypoint_found` 只表示找到了 HTML 文件且基本静态资源检查通过，不表示已人工验证可玩。需要构建步骤、后端或密钥的项目不会被错误标成可直接试玩。

## 证据审核与隔离保护

第三方索引的模型声明不是事实认证。模型归属、原始 Prompt、人工参与、入口路径和实际运行结果分别记录。编辑 `config/research_reviews.json` 后执行：

```bash
python3 scripts/review_evidence.py                     # 只校验，不写数据库
python3 scripts/review_evidence.py --apply              # 显式确认才写入
python3 scripts/build_catalog.py --check
python3 scripts/build_site.py
```

审核记录必须附上直接的 HTTPS 来源。数据库保留 `research_review_history` 修改历史；重新导入社区来源不会覆盖人工审核层。浏览器测试器见 [docs/BROWSER_SMOKE.md](docs/BROWSER_SMOKE.md)，HTTP 与 WebSocket 均进行浏览器层拦截，但仍必须在无密钥、无外网的隔离容器/VM 中运行。**浏览器加载成功不等于作品真正可玩。**

旧版 `refresh_community_indexes.py` 仍可用于实验性候选归并，但其输出隔离在 `data/community/`；不得把它直接当作正式去重作品表。

## 数据更新

```bash
# 先只比较四个主来源，默认不写库
bash scripts/refresh_all.sh --dry-run

# 核对来源更新后再写入版本化证据快照并重新构建
bash scripts/refresh_all.sh --write

# 如需重新采集第三方源码，需要单独授权并显式执行
python3 scripts/collect_repositories.py --dry-run
python3 scripts/collect_repositories.py --repo OWNER/REPO
```

可选设置 `GITHUB_TOKEN` 提高 GitHub API 速率限制。只需公开仓库只读权限；不要把 Token 写入代码、配置文件或提交记录。

## 安全、许可证和边界

- 收录公开仓库不等于获得再分发许可；每个项目都应遵循上游 LICENSE。
- `NOASSERTION` 表示没有确认许可证，不代表 MIT 或可自由商用。
- 第三方游戏只通过移除 `allow-same-origin` 权限的 sandbox iframe 运行；网页不会再从 jsDelivr 加载 HTML。公开发布第三方源码需要先配置 `config/publication_approvals.json`。
- 不执行不可信源码中的构建脚本；需要构建的项目先标记为 `requires_build`，等待人工审查。
- 不保证所有作品都能直接运行：依赖后端、私有 API、环境变量或构建产物缺失的项目，需要单独适配。
- GitHub Pages 有站点容量限制。建议 `games/_repos/` 总量控制在 1 GB 以下；过大的媒体资源应改用 Git LFS 或外部静态资源托管。

参见 [docs/COLLECTOR.md](docs/COLLECTOR.md)、[docs/PAGES.md](docs/PAGES.md)、[docs/SECURITY.md](docs/SECURITY.md)。

## 审查加固版：公开发布与本地预览

**默认不把未核验许可证的 GitHub 仓库复制进公开 Pages 站点。** `config/publication_approvals.json` 默认是空白名单，即便已在本地下载，也只展示目录、原作者演示与仓库链接。检查每个上游 LICENSE、图片/音乐等素材授权后，可以逐项将其加入 `approved_repositories`。

```bash
# 仅本地测试：临时包含全部采集到的 HTML；生成物不得直接部署公开
python3 scripts/build_site.py --preview-unapproved
python3 -m http.server 8000 --directory site

# 公开站点：只包含经过授权的仓库
python3 scripts/build_site.py
```

当前播放器使用本仓库 `site/games/` 的静态文件，限制性 iframe 沙箱不会取得与目录页相同的脚本 Origin；但跨域依赖较多的游戏可能无法正常运行。不要为了“让游戏能跑”随意加回 `allow-same-origin`。

深度问题清单、验证边界与后续优先级见 [审查报告](docs/REVIEW_2026-11-16.md)。
