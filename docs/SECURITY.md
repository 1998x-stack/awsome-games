# 第三方源码与浏览器隔离

本仓库收录第三方游戏和创意作品。仓库公开不等于代码获得再分发许可。

- 每个仓库单独记录许可证；缺少许可证时 `license_spdx=NOASSERTION`。
- 不执行克隆仓库中的安装脚本、构建脚本、二进制文件或游戏代码。
- 不复制 `.env`、密钥、证书和凭据文件。
- 不复制 `.git`、`node_modules`、虚拟环境和缓存目录。
- GitHub Pages 播放器使用同站静态文件，但在 iframe sandbox 中不授予 allow-same-origin，也不允许顶层导航。默认不发布未批准的第三方源码。
- 不给第三方游戏授予父页面 DOM 访问能力；播放器不把游戏脚本注入目录页面。
- 若发现凭据泄漏、恶意脚本或侵权内容，应停止发布该快照并从索引中标记/移除。

如果希望进一步提高隔离等级，下一步应把每个游戏托管在独立 origin，并加入 CSP、Playwright 无凭据 smoke test 和依赖清单扫描。

- 不应仅依据 GitHub API 的 `license_spdx` 自动判定游戏素材允许再分发；必须逐项核查。
- 防止 `--preview-unapproved` 本地构建产物被提交到公开 Pages。
- 详情请看 `docs/REVIEW_2026-11-16.md`。
