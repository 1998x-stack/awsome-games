# GitHub Pages 部署与试玩（review 版）

`.github/workflows/pages.yml` 由 main 提交触发，构建 SQLite JSON 投影、校验基础安全规则、上传 Pages artifact 并部署。首次在 Settings → Pages → Build and deployment → Source 选择 GitHub Actions。

## 试玩安全策略

- **不使用 jsDelivr 加载 HTML**：其 HTML content-type 被强制设为 `text/plain`，无法作为网页运行。
- 使用 `./games/_repos/<owner>__<repo>/...html` 作为发布入口；只有在 `config/publication_approvals.json` 核准的仓库文件才进入网站制品。
- iframe 允许 `allow-scripts`、`allow-pointer-lock`、`allow-forms`、`allow-modals`，**不允许 `allow-same-origin`**、顶层导航和弹窗。游戏在不透明 origin 中运行。
- 不默认开放本地游戏的直接新窗口链接，因为打开同源 HTML 会破坏 sandbox 的安全属性；外部作者演示可通过单独链接打开。
- 游戏无法运行可能是 sandbox 限制、绝对路径、跨域 fetch、CDN 被拦截或资源缺失，不能将它视作验证通过。
- 长期应迁到独立域名的游戏沙箱站点，隔离目录站点与原始游戏静态文件。

## 批量采集与发布

1. `python3 scripts/collect_repositories.py --limit 2`
2. `python3 scripts/build_catalog.py && python3 scripts/check_catalog.py`
3. 对上游许可证和素材逐一核验，填入 `config/publication_approvals.json`
4. `python3 scripts/build_site.py`
5. `python3 -m http.server 8000 --directory site`
6. 提交 Git，使用 Pages Actions 部署。

本地研究预览允许 `--preview-unapproved`，但 **不得把该预览产物公开部署**。

## 容量限制

GitHub Pages 已发布网站的官方上限为 1GB。本项目在 build_site 阶段默认设置 850 MiB 容量阈值。单个上游仓库的采集上限不是整个 Pages 的许可用量；不应盲目把所有游戏完整快照上传到公开仓库。

https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
