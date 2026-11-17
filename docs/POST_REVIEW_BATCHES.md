# M1 · 原帖审核批次（固定快照）

来源：[`data/research/v1/entities.json`](../../data/research/v1/entities.json)，截至 `2026-11-17` 的历史候选。**帖子线索不是独立游戏，队列不表示已获作者授权。**

| 批次类型 | 优先级 | 原帖数 | 分批数 | 下一步判定 |
|---|---|---:|---:|---|
| `P00_MAPPED` | P0 | 2 | 1 | Existing mapped links need independent verification |
| `P01_CANDIDATE` | P0 | 1 | 1 | Existing candidate links must not be promoted without direct evidence |
| `P10_REPO_LEADS` | P1 | 19 | 1 | Verify linked source repositories and same-author relationship |
| `P20_GAME_PLAY` | P1 | 175 | 7 | Confirm original playable endpoint and whether one post maps to multiple works |
| `P21_OTHER_PLAY` | P2 | 6 | 1 | Determine whether the demo is an interactive work or another artifact |
| `P30_GAME_NO_LINK` | P2 | 99 | 4 | Request original work or source evidence; avoid title-only joins |
| `P40_OTHER_NO_LINK` | P3 | 33 | 2 | Classify category before matching to game |
| `P50_VIDEO_SCENE_TOOL` | P3 | 572 | 23 | Triage non-game and non-playable posts before work matching |

合计：907 条帖子线索 / 40 个 ≤25 条审核工单；已有精确映射 2、候选 1、未归并 904。所有条目初始 `UNREVIEWED`。

**人工验收标准：** 必须核对原帖或作者原始仓库等 HTTPS 一手证据，记录创作者身份、归属类型（原作/镜像/复刻/PR/工具/视频）、作品入口与反证。不得用标题相同直接合并；可一帖多作品，也可能一作品多帖。APPROVED 的证据必须满足 `review_evidence.py` 的验证，不能仅凭排队类型升级。M3 仍等待人工确认。

机读完整工单：[`data/research/review_batches/2026-11-17.json`](../../data/research/review_batches/2026-11-17.json)。每个工单包含原帖 ID、原帖 URL、来源和原始链接线索；不包含私有凭证或第三方源码。
