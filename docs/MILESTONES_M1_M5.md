# M1–M5 实施台账（2026-11-17）

此文档记录真实落地的代码组件和未完成工作。**目前没有任何第三方游戏的运行与交互通过认证。**

## M1：原帖、模型与 Prompt

- 原始 1,118 条来源记录，907 条原帖实体线索，64 项研究工程，83 个候选仓库维持不同统计口径。
- 对 research_posts.model_claim 的源索引污染进行拆分：原来误填的 prompt shared / not shared 被标记到独立的 research_post_prompt_evidence；不改动 v1 冻结 JSON，保留原始文本。
- 仅允许直接审核 manifest 才能覆盖 source-derived 的评估；原帖候选不会因相似标题自动归并。
- config/work_aliases.json 显式登记 Last Return 与 Last Return（原 No Return）的 **CANDIDATE** 关系；仍未人工批准，不能当作独立原作认证。

未完成：约 904 条未归并原帖需逐条证据审核；更多别名、旧库关系、作者与模型归属仍未复核。

## M2：候选仓库准入

- scripts/review_queue.py 从 SQLite 生成三个独立审核队列；83 个仓库中 32 个不在旧源码采集器内。
- 分类仅是下一步审查路由（浏览器候选、镜像、PR、非浏览器工程、工具等），不自动克隆、导入旧库或宣称原作。
- 新的 /review.html 只读网页列出审核路由与原始证据，并连接 /research.html 的记录详情。

未完成：83 个候选的完整文件扫描、第三方依赖核验、原作者及素材许可证逐项确认。

## M3：浏览器运行报告证据

- scripts/import_browser_report.py 接收已在独立容器/VM 中完成的 browser_smoke.py 报告；只有显式 --write 才存库。
- 入口必须与 research_works 中的已审静态入口一致；锁定 40 位 Git commit SHA，并从可信本地 staging 文件计算 HTML SHA256。
- 每次导入的 evidence_id 内容寻址、重复导入幂等；browser_load 仍然不授予 GAMEPLAY_VERIFIED。
- 研究作品详情可显示最近一条浏览器载入报告及 Git/SHA，但默认没有任何第三方报告。

未完成：无外网容器/VM、实际 11 个静态入口运行、交互断言及媒体制品公开审阅。请勿在宿主机运行不可信代码。

示例（仅在完成独立隔离环境配置、来源和入口审查后）：

```bash
python3 scripts/browser_smoke.py --root /isolated/staged --entry demos/04-fps/index.html --report /isolated/smoke.json
python3 scripts/import_browser_report.py --work-id F52-W012 --repo-commit <FULL_40_HEX_SHA> \
  --root /isolated/staged --report /isolated/smoke.json \
  --browser-version 'Chromium (record actual version)' --environment 'disposable VM/OS details' --write
```

## M4：数据自动化

- .github/workflows/research-sync.yml 每日 UTC 03:17 触发四个上游 JSON 元数据来源的**只读**漂移检查，保留运行制品。
- 不进行自动向 main 写回、不克隆、不执行第三方程序。若来源缩减，脚本应按安全策略失败并提示人工核对。
- 原有 data/research/current/ 内容寻址快照、审批历史与默认封闭发布策略继续保留。

未完成：覆盖 9 个全部列明的来源、定期 PR 提案与审查签核、持续链接有效性监测、数据迁移框架。

## M5：关联网站

- 网站提供 /research.html (来源证据) 与 /review.html (审查待办)，分别标记归属/Prompt 与浏览器证据。
- /review.html 安全 textContent 渲染，不对不可信 URL 自动提权、写库或执行脚本。
- 数据经 build_site.py 的同一 staging/rollback 逻辑输出 site/data/review-queue.json，不引入新的未授权游戏代码。

未完成：全设备视觉验收、跨原帖多对多实体导航、真正的交互审核后台、截图归档与公开可玩游戏。

## 运行质量检查

```bash
python3 scripts/build_catalog.py --check
python3 -m unittest discover -s tests -v
python3 scripts/check_catalog.py
python3 scripts/build_site.py
node --check site/assets/research.js
node --check site/assets/review.js
```

源码处理原则：链接不等于源码、源码不等于授权、HTML 入口不等于可玩、作者陈述不等于独立复现、Prompt 状态不等于模型身份。
