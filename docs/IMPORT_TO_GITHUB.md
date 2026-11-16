# awsome-games GitHub 初始化与源码采集

核心源码、脚本、SQLite 数据库和工作流已提交到 [1998x-stack/awsome-games](https://github.com/1998x-stack/awsome-games) 的 `main` 分支，**无需再解压历史 ZIP**。

```bash
git clone https://github.com/1998x-stack/awsome-games.git
cd awsome-games
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 scripts/build_catalog.py --check
python3 scripts/collect_repositories.py --dry-run
python3 scripts/collect_repositories.py --limit 2
```

如果需要重新生成稳定 ID 种子，可运行 `python3 scripts/export_seed.py`；它从 SQLite 导出恢复快照，并非原始第三方数据逐字备份。

首次启用 Pages：**Settings → Pages → Build and deployment → Source → GitHub Actions**。启用后到 Actions 手动重跑 `Build and deploy GitHub Pages`。

网页默认只展示公开作品索引；第三方代码的公开发布需要检查许可证，并在 `config/publication_approvals.json` 手工批准。