# 将初始源码包导入 1998x-stack/awsome-games

当前初始化包包含完整源码、分类 Schema、155 条种子记录和 SQLite 数据库。将 ZIP 解压到目标仓库根目录即可。

```bash
git clone https://github.com/1998x-stack/awsome-games.git
cd awsome-games
unzip -oq ~/Downloads/awsome-games-source.zip -d .
bash bootstrap.sh

git add -A
git commit -m "feat: bootstrap Fable games catalog and Pages site"
git push origin main
```

推送后，`.github/workflows/pages.yml` 会生成静态目录并部署 GitHub Pages。首次使用需要在仓库 Settings → Pages 中将 Source 设置为 GitHub Actions。

完成源码导入后，按 README 中的说明运行 `python3 scripts/collect_repositories.py --dry-run`，再采集全部仓库。
