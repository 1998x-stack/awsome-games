# 浏览器隔离检查 / Browser Smoke Testing

测试目标：在可丢弃的 Chromium 浏览器环境中检查**静态 HTML 是否加载**，记录网络依赖、控制台错误、iframe 安全边界和截图。该测试不能自动证明游戏关卡、物理交互或 AI 生成过程的正确性。

## 必须满足的约束

- 在没有秘密、无登录 Cookie、无持久化浏览器用户资料的 disposable VM / container 内运行。避免挂载私有文件系统。
- 只从选择并已审查过的本地静态文件夹读取资源，不执行上游项目的 npm install / build / 二进制程序。
- 浏览器网络仅允许测试进程使用的 127.0.0.1 临时端口，其余 HTTP/HTTPS 请求全部拦截。
- iframe 使用 allow-scripts、allow-pointer-lock、allow-forms、allow-modals，但**不添加 allow-same-origin**。
- 默认关闭下载、Service Workers、摄像头和麦克风权限。
- CDN/外部字体/WebSocket 如被阻断，必须如实记为依赖问题，不绕过隔离强行放开。

安装（仅在隔离环境）：

    python3 -m pip install playwright
    python3 -m playwright install chromium

将经过静态审计的项目 HTML 与相对静态资源置于隔离文件夹：

    python3 scripts/browser_smoke.py \
      --root /work/staged-game \
      --entry index.html \
      --report /tmp/research/smoke.json \
      --screenshot /tmp/research/smoke.png

测试脚本输出：
- BROWSER_LOAD_CHECKED：frame body 存在、无法读取父文档、未捕获明显 JS 错误或外部网络依赖请求；仅证明基本浏览器加载。
- INCOMPLETE_OR_FAILED：存在异常、被拦的运行依赖或沙箱不满足。
- GAMEPLAY_VERIFIED：**本脚本不会自动输出**，必须由人工设计交互断言与检查证据，才能独立确认。

建议长期记录：GitHub commit SHA、浏览器/OS、HTML SHA256、启动耗时、点击/键盘操作及预期结果、截图、console errors、资源清单、阻断网址、错误原因、许可证核对。

**现状**：浏览器隔离执行器已纳入代码；并未在这轮研究中真正完成全部第三方游戏的交互验证。网站静态“发现 HTML 入口”数量不可当作实测数。
