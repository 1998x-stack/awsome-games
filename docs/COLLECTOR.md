# 源码采集器

核心脚本：`scripts/collect_repositories.py`。

## 它具体做什么

1. 从 `data/catalog.sqlite` 读取去重后的仓库清单；一个 GitHub 仓库只克隆一次。
2. 可选调用 GitHub REST API 读取默认分支、Stars、Forks、许可证、归档状态等元数据。
3. 使用浅克隆获取公开仓库，不递归初始化 submodule，不执行 npm/pnpm/yarn、Makefile、Shell 或其他仓库脚本。
4. 用 `git ls-files` 获取被版本控制的文件清单。
5. 将代码快照复制到 `games/_repos/<owner>__<repo>/`，保留 HTML、CSS、JS/TS、图片、音频、字体、模型和静态资源。
6. 排除 `.git`、`node_modules`、缓存、虚拟环境、`.env`、密钥文件等；大于文件阈值或超出仓库总量阈值的文件会跳过并记录。
7. 根据人工 override、索引中的明确文件链接、作品名称与 HTML 路径匹配，寻找 `index.html` 等入口。
8. 更新 `repositories`、`project_repositories`、`repository_files`、`projects` 和 `ingest_runs`。

## 最常用命令

```bash
# 首次导入数据库
python3 scripts/build_catalog.py

# 先查看会采集哪些仓库，不产生克隆
python3 scripts/collect_repositories.py --dry-run

# 先只克隆 2 个仓库做验证
python3 scripts/collect_repositories.py --limit 2

# 克隆全部 54 个唯一仓库
python3 scripts/collect_repositories.py

# 只处理指定仓库，可重复传入 --repo
python3 scripts/collect_repositories.py --repo MiaAI-Lab/Claude-Fable-5.2-HTML-Files

# 强制重新克隆并刷新源码快照
python3 scripts/collect_repositories.py --force

# 更新数据库导出和网站
python3 scripts/build_catalog.py
python3 scripts/build_site.py
python3 scripts/check_catalog.py
```

## 如何确定一个作品的 HTML 入口

优先级从高到低：

1. `config/project_overrides.json` 中的 `entry_path`；
2. 种子记录指向仓库内具体 HTML 文件的 GitHub `blob` 链接；
3. Fable Arcade 等合集仓库可从其明确的作品目录 URL 推导；
4. 仓库只有一个 HTML 文件时使用该文件；
5. 作品标题与文件路径明显匹配时使用该文件；
6. 其余情况标记 `ambiguous_html_entrypoints` / `needs_review`，不猜测。

如果自动识别错误，可以在 `config/project_overrides.json` 里指定：

```json
{
  "projects": {
    "fab_0123456789abcdef": {
      "entry_path": "public/index.html",
      "route": ""
    }
  }
}
```

`entry_path` 是仓库根目录相对路径。修改后再次运行采集器即可。

## 本地试玩

```bash
python3 scripts/build_catalog.py
python3 scripts/build_site.py
python3 -m http.server 8000 --directory site
```

访问 `http://localhost:8000`。只有经 `config/publication_approvals.json` 核准发布的仓库才显示本站“尝试试玩”。本地隔离预览可使用 `python3 scripts/build_site.py --preview-unapproved`，此产物不得公开发布；网页使用同站静态文件的 sandbox iframe（无 allow-same-origin），不依赖 jsDelivr HTML。

## 安全边界

采集器只克隆和静态复制文件，不执行第三方项目。默认不会运行 `npm install` 或 `npm run build`。只有源码、没有静态 HTML 产物的 React/Vite/Next 等项目会被标记为 `requires_build` 或 `needs_review`，需要人工审查后再决定如何构建。

## 失败恢复与资源完整性

修订后的采集先把 Git 跟踪文件复制到 `.partial-*` 临时目录；成功后才替换此前快照。读取/复制异常时保留旧文件。源目录内不跟随符号链接，越界路径或敏感文件被过滤。静态 HTML 中显式引用的脚本、样式、图片、音视频缺失时标注 `missing_assets`，并在映射的 `note` 中记录路径。该分析不覆盖运行时动态 fetch/依赖。


## 采集数据与文件快照双重回滚（2026-11-17）

库文件与 SQLite 库存需要保持版本对应。新流程先复制安全 Git 跟踪文件到暂存目录，替换源目录时**保留旧目录备份直到数据库提交成功**。若 HTML 入口推断、静态资源检查或 SQLite 写入失败，先回滚数据库事务，再恢复旧源码快照；已有成功采集记录不会仅因本次刷新失败就被标为不可用。

人工入口配置不允许 `../index.html`、`./index.html`、绝对路径或反斜杠路径；不能通过去除前缀的方式“修复”有风险的配置。失败和恢复异常写入 ingest_errors，供人工复查。

