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


## 网络拦截的准确边界（2026-11-17 审查）

在 Playwright 1.48 及以后版本中，`context.route_web_socket` 可拦截新的 WebSocket。运行器现在**要求该接口存在**，并关闭所有 WebSocket；同时记录被阻断的外部 HTTP、WebSocket、HTTP 4xx/5xx 和加载失败请求。凡是有阻断请求/控制台错误的测试不能标为 BROWSER_LOAD_CHECKED。

**重要：** Playwright 的网络路由不是操作系统防火墙，无法严格证明所有 WebRTC/UDP、浏览器内部网络功能都无法访问外网。真正运行不可信第三方程序时，应在无出站网络权限的 disposable VM/网络命名空间内进行，并确保没有主机文件挂载、登录 Cookie、密钥或本机服务。单凭 iframe sandbox 不足以承诺恶意代码 100% 安全。

Official API: https://playwright.dev/python/docs/api/class-browsercontext#browser-context-route-web-socket


## 已实现的 OS 级隔离执行器（2026-11-17）

浏览器层路由只是第二道防线，无法阻断 WebRTC/UDP/DNS。真正的边界由容器网络命名空间提供：

    # 一次性构建（此步骤需要网络，仅用于获取固定版本的工具与浏览器）
    docker build -f scripts/isolation/Dockerfile.smoke -t awsome-games-smoke .

    # 在 --network none 下运行（不建议把待测目录放在 /private/tmp，macOS 的 Docker VM 可能看不到）
    bash scripts/isolation/run_isolated_smoke.sh \
      --root .cache/isolated-stage --entry demos/04-fps/index.html --out .cache/iso-reports \
      --screenshot smoke.png \
      --browser-version 'chromium-headless-shell <实际版本>' \
      --environment 'docker --network none / python:3.12-slim-bookworm / uid 65534'

该包装脚本强制执行：`--network none`、只读根文件系统、只读挂载被审查目录（挂载点不可写，页面无法篡改其来源证据）、`--cap-drop ALL`、`no-new-privileges`、`--pids-limit 256`、内存/CPU 上限、以 uid 65534 运行、`/reports` 使用命名卷（macOS 绑定挂载不遵循容器 uid）。脚本在启动前还会预检容器是否真的能看到目标入口，避免“挂载为空”被误读成测试失败。

**已验证范围：** 2026-11-17 在本仓库自编写的无害 fixture（`.cache/isolated-stage`，非第三方代码）上跑通，得到 `BROWSER_LOAD_CHECKED`、`iframe_isolation: true`、无控制台错误、无阻断请求，并保存截图。**第三方游戏仍未在此隔离环境中执行：保持 `NOT_TESTED`。**

自报浏览器报告无法被冒用：`scripts/import_browser_report.py` 只接受与 `research_works.entry_path`（已人工审阅的入口）完全一致的 staged 文件，并锁定 40 位 commit SHA。用自编 fixture 去冒领真实 work_id 会被拒绝，`research_runtime_evidence` 保持 0 行。



## 交互实测与依赖分级（2026-11-17 新增）

### 两级结论，必须分开

| 层级 | 工具 | 含义 |
|---|---|---|
| 加载 | `scripts/browser_smoke.py`（`--mode smoke`） | `BROWSER_LOAD_CHECKED`：body 加载、iframe 隔离成立、无功能性阻断 |
| 交互 | `scripts/browser_gameplay_probe.py`（`--mode gameplay`） | `INPUT_RESPONSIVE`：注入 15 个真实指针/键盘手势后，**渲染输出发生变化** |

`INPUT_RESPONSIVE` **不等于**游戏正确、完整或可玩得好；它只证明"有东西在监听输入并作出反应"。刻意不提供比这更强的自动结论。

探针的判据（全部记录哈希，不写散文）：

1. 载入后先静置取样 → `initial_pixels`、`initial_dom`；
2. 再静置 `--idle-ms` → `idle_pixels`（区分"持续动画"与"响应输入"）；
3. 注入手势：鼠标移动到中心、4 次点击、10 个按键（方向键/WASD/Space/Enter）→ `after_input_pixels`；
4. 只有 `after_input_pixels != idle_pixels`（或 DOM 指纹变化）且**无控制台错误、无功能性阻断、iframe 隔离成立**时才判定通过。

自检对照（自编写 fixture，非第三方）：会响应输入的页面 → `INPUT_RESPONSIVE`；完全静态的页面 → `NO_OBSERVABLE_RESPONSE`；会抛错的页面 → `INCOMPLETE_OR_FAILED`。

### 依赖分级：字体/图标不上纲上线，功能性依赖仍 fail closed

`browser_smoke.py` 的 `is_cosmetic_request()` 把 **web 字体与 favicon** 视为样式性依赖，用一个**本地空响应**满足它们（`stubbed_cosmetic_requests`），因此：

* **零外联仍然成立**——不是放行，而是本地 stub；
* 只缺字体不再被误判为"运行失败"，因为字体几乎从来不是功能前提；
* 脚本、`fetch`/XHR、媒体、wasm、WebSocket 一律仍是**功能性**依赖，被阻断即 fail closed。

### 命令

    # 加载检查
    bash scripts/isolation/run_isolated_smoke.sh --root .cache/isolated-stage/<x> \
      --entry index.html --out .cache/iso-out

    # 交互实测
    bash scripts/isolation/run_isolated_smoke.sh --mode gameplay --root .cache/isolated-stage/<x> \
      --entry index.html --out .cache/iso-out --screenshot shot.png

    # 聚合成可复核证据（fail-closed 校验）
    python3 scripts/build_runtime_evidence.py --out data/reports/runtime-evidence.json \
      --capture '{"repo":"o/n","commit":"<40hex>","entry":"index.html","probe":"gameplay","report":".../gameplay.json"}'

### 已知的沙箱不兼容类别（实测发现）

站点 iframe 沙箱**必须**不含 `allow-same-origin`，因此任何在初始化阶段访问
`localStorage` / `sessionStorage` / `IndexedDB` 的产物都会抛
`SecurityError: The document is sandboxed and lacks the 'allow-same-origin' flag` 而无法运行。
实测样本 `Time-dev-alt/Fable-5.1-Games@ddfba6c4` 的 `shooter.html` 即属此类，已记为
`playable_status=sandbox_incompatible` 且不参与发布。**不要为了让它运行而放开同源权限。**
