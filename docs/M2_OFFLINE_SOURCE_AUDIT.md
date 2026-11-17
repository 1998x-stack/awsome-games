# M2 · 完整本地只读源码扫描指引

首次通过 GitHub API 对 7 个固定提交的 850 个 Git 文件做了树级元数据盘点，
并全文检查了 11 个已定位入口 HTML。真正完整的多文件代码级扫描必须再读取各仓库的
其余文本/源码文件，而不能从“有 HTML 入口”推断可玩。新增工具
`scripts/audit_local_source_tree.py` 在固定 Git 提交的本地对象数据库中逐个读取 blob，
**不执行第三方代码、npm install、构建、原作者程序或游戏**。

使用前由人工独立取得仓库快照；下载阶段本身应评估仓库安全、
Git LFS/子模块与磁盘限制。当前工具**不负责下载、签名验证或自动 clone**。

| 仓库 | 固定 Git commit | 研究工程 |
|---|---|---|
| realcodebear/saltline-fable-5.2 | `09c51774cd77aad750bd2d6c42af2b1020cb668d` | F52-W010 |
| wquguru/fable52-fps-repro | `a7e1df3ce32eb2bb05e23ae457fe5fe2bffab961` | F52-W012 |
| SharpWizard/ironvale | `41672ef32a42c154b237e579cdf357144709204a` | F52-W006 |
| DNDNoob/EmberDeep | `53db7db90ed299cc4de11d21f631bc9bd120e5ec` | F52-W034 |
| GavinLOrio/Fable-5.2-random-game | `447d0b5a7947fed9f2916c151c5aaf41522a96b1` | F52-W004, F52-W005 |
| S77FFY/daedalus | `be77f2f3d6ff11127684654617f157c5ef9f545e` | F52-W035 |
| hahaliu1029/fable5.2demo | `97710fad3ca3cbfb6e91b852644bc513ace0a342` | F52-W018–021 |

```bash
# 本工具假设 /sandbox/pinned-src/ironvale 是已人工取得、已核对的不可变 Git 工作副本。
# 它会检查 HEAD 完全等于预期 commit，不会切换分支、git fetch、安装或运行代码。
python scripts/audit_local_source_tree.py \
  --root /sandbox/pinned-src/ironvale \
  --repo SharpWizard/ironvale \
  --commit 41672ef32a42c154b237e579cdf357144709204a \
  --output data/research/audits/repos/sharpwizard__ironvale-full.json \
  --write
```

报告包含所有跟踪 Git 路径、Git blob SHA、字节数、文本 SHA-256、请求/脚本相关词法线索、
第三方主机字面量、Package Manifest 声明的依赖和脚本名称。超过阈值、链接和二进制只记录
元数据，不执行，不读敏感文件内容。**即使所有可读文本完成扫描，依赖供应链风险、
镜像与原作者关系、图片/音频/字体权利、外网实际访问和游戏行为仍待单独核验。**
下一轮 Pi Agent 将全量报告引入 PR 后，审核人必须检查异常静态信号与真实许可文书。
