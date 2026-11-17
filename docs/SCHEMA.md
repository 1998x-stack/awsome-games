# 数据库 Schema

主数据库为 `data/catalog.sqlite`，采用 SQLite；网页端使用由数据库导出的 `site/data/catalog.json`。关系型数据库负责规范化与采集状态，JSON 负责静态网站读取。

## 实体关系

```mermaid
erDiagram
  PROJECTS ||--o{ PROJECT_CATEGORIES : classified_as
  CATEGORIES ||--o{ PROJECT_CATEGORIES : contains
  PROJECTS ||--o{ PROJECT_REPOSITORIES : sourced_from
  REPOSITORIES ||--o{ PROJECT_REPOSITORIES : contains
  PROJECTS ||--o{ LINKS : has
  PROJECTS ||--o{ PROMPTS : has
  PROJECTS ||--o{ PROJECT_EVIDENCE : supported_by
  EVIDENCE_SOURCES ||--o{ PROJECT_EVIDENCE : documents
  REPOSITORIES ||--o{ REPOSITORY_FILES : inventories
  INGEST_RUNS ||--o{ INGEST_ERRORS : records
```

## 核心表

| 表 | 主键 | 作用 |
|---|---|---|
| `projects` | `id` | 作品本身；一条作品记录不等于一个仓库 |
| `categories` | `id` | 规范化分类词表 |
| `project_categories` | `(project_id, category_id)` | 多标签分类，保留原始分类标签 |
| `repositories` | `id` | 去重后的 GitHub 仓库，保存分支、许可证、克隆状态和 commit SHA |
| `project_repositories` | `(project_id, repository_id)` | 作品与仓库多对多映射，记录原作/镜像/合集关系和入口文件 |
| `links` | `id` | 在线演示、作者原帖等公开链接 |
| `prompts` | `id` | Prompt 的公开状态、原文链接和可选文本 |
| `evidence_sources` | `id` | 索引、帖子、原始仓库等证据来源 |
| `project_evidence` | 复合键 | 作品与证据的关系、证据类型和置信度 |
| `repository_files` | `id` | 克隆仓库的文件清单、扩展名、大小、SHA-256 和 HTML 入口标记 |
| `aliases` | 复合键 | 作品别名和历史名称 |
| `ingest_runs` | `id` | 每次采集运行的统计和状态 |
| `ingest_errors` | `id` | 克隆、解析、入口识别错误 |

## 重要字段语义

- `model_claim`：社区/作者对生成模型的声明，不等于独立验证。
- `model_confidence`：当前种子默认 `community_claim`。
- `relation_type`：`creator_original`、`third_party_mirror`、`collection`、`community_indexed_source`、`unverified_source_candidate`。
- `entry_confidence`：`explicit_override`、`source_link`、`title_path_match`、`unique_html`、`unresolved` 等。
- `playable_status=entrypoint_found`：只表示找到了 HTML 入口，不表示已经人工试玩或端到端验证成功。
- `license_spdx=NOASSERTION`：没有确认许可证；公开仓库不等于允许再分发。

## 初始数据快照

`data/seeds/games_52.tsv`、`games_51.tsv` 和 `mia_html_52.txt` 是可复现的紧凑种子清单；结合 5 个重点作品和 2 个额外单文件游戏，可重建首批 155 条作品。首轮导入后得到 54 个去重仓库、150 条作品-仓库关系。重复仓库只克隆一次，合集仓库里的多个作品仍是多条项目记录。

## 研究层表结构（2026-11-17）

基线表 projects、repositories、project_repositories 不重建、不自动提升社区模型声明。新增表的分工：

| 研究表 | 粒度与职责 |
|---|---|
| research_source_records | 按 (source, source_id) 保存当前来源快照；只计当前版本，不把旧删除数据算作新增 |
| research_posts | 精确 X status ID 作为帖子身份；缺失 ID 使用孤儿键；不等于独立游戏 |
| research_repositories | 83个 GitHub 候选仓库及与原创/镜像/工具/PR 的关系 |
| research_works | 64个作品工程映射、源码入口、Prompt/外部资源/人工贡献的源声明 |
| research_claims | 反证与模型归属冲突 |
| research_project_links | 旧目录到研究主表的保守精确映射，允许保留人工设置的关系 |
| research_work_reviews | APPROVED/DRAFT/REJECTED 的作品人工审核字段，独立于来源快照 |
| research_post_reviews | APPROVED/DRAFT/REJECTED 的原帖归并审核 |
| research_review_history | 只追加审核变更时间和依据，重复审核内容不制造伪新历史 |
| research_ingest_meta | 当前已经入库的来源快照 capture date |
| research_browser_runs | 将来真正浏览器实测的日志；空白不是已通过 |

一个 Work 可以关联多个来源帖；一个 GitHub 仓库也可能对应多款不同作品；同名和同仓库绝不能自动推断唯一作品。人工审核必须有直接证据 URL，不能修改来源冻结 JSON 再冒称作者事实。active manifest 的 SHA-256 对 sources/entities 两文件一起做内容校验，详见 RESEARCH_INTEGRATION.md。
