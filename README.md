# awsome-games

AI 游戏与创意编程作品数据库、GitHub 源码采集器和 GitHub Pages 在线试玩站点。

## 初始化状态

目标仓库已初始化。完整源码、SQLite 数据库和 Pages 前端已整理为初始源码包 **awsome-games-source.zip**，并在维护会话中交付。将源码包解压到本仓库根目录后，即可使用下述脚本。

当前首批数据快照：

- 155 条作品记录（Fable 5.1：10；Fable 5.2：145）
- 54 个去重 GitHub 仓库入口
- 150 条作品—仓库关系
- 59 个在线演示链接
- 76 个单文件 HTML 视觉实验

## 导入源码包

在本地克隆本仓库，并将交付的 ZIP 解压到仓库根目录：

```bash
git clone https://github.com/1998x-stack/awsome-games.git
cd awsome-games
unzip -oq ~/Downloads/awsome-games-source.zip -d .
bash bootstrap.sh
git add -A
git commit -m "feat: bootstrap Fable games catalog and Pages site"
git push origin main
```

## 采集游戏源码

导入源码后：

```bash
python3 scripts/collect_repositories.py --dry-run
python3 scripts/collect_repositories.py --limit 2
python3 scripts/collect_repositories.py
python3 scripts/build_catalog.py
python3 scripts/build_site.py
python3 scripts/check_catalog.py
```

核心采集器会对 GitHub 仓库去重、浅克隆、复制 HTML/CSS/JS 和静态资源、识别游戏入口，并把状态写入 SQLite。它不会执行第三方仓库的 npm 安装或构建脚本。

## GitHub Pages

源码导入后，在仓库 **Settings → Pages → Build and deployment → Source** 中选择 **GitHub Actions**。之后推送到 `main` 会触发 Pages 构建与部署。

详细说明见源码包中的 `README.md`、`docs/SCHEMA.md`、`docs/COLLECTOR.md`、`docs/PAGES.md` 和 `docs/SECURITY.md`。

> 作品收录不代表取得再分发授权。部署第三方源码前，请核对上游许可证。发现 HTML 入口也不等于已经人工试玩验证。
