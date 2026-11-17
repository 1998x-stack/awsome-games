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


## 发布与审查加固补充

- `build_site.py` 对已批准仓库也只复制受支持静态资源；显式阻止密钥类文件、符号链接、路径逃逸及未审查的脚本/可执行制品，并先在站点目录外构建。
- `--preview-unapproved` 不得在 CI/Pages 中执行。所有 Pages 发布现在在上传之前通过 Python、JavaScript、数据库及发布器安全回归检查。
- 直接访问与目录页同一 Origin 的第三方 HTML 仍存在浏览器安全边界；iframe 的不透明 Origin 只保护嵌入式加载。即便已经获得再分发许可，后续规模化运行也应优先将第三方游戏迁往**独立域名**。
- 浏览器 smoke test 阻断 HTTP/HTTPS 和 WebSocket 请求，并记录异常，但仍需单独的 VM/网络隔离来防御 WebRTC/UDP 和其他底层连接。
- 不应仅凭模型版本、GitHub Stars、社区标签或源码存在推断实际试玩通过。审核证据表独立于来源快照。

