# PDF 提取重构进度（2026-09-24）

本文件记录原型结果；候选是局部窗口，不代表整页或整本书达到人工审阅标准。原始响应、请求和 CCEF 重放位于 git 忽略的 `data/debug/extraction-audit-20260924/`。经操作者明确授权，真实调用只发送所选测试页的文字和必要图示信息，没有上传整本 PDF；保留全部尝试，包括失败输出。

| 阶段 | 当前结果 | 尚未解决 |
| --- | --- | --- |
| P0 | 离线读取历史运行、PDF 身份与固定窗口；Catalan p6–9 历史 4 次均失败，Scandinavian p319–323 历史 13 次混合成功/失败/取消。最小人工 oracle 见 `pdf-extraction-p0-baseline.md`。 | 21 窗口仍未做人工 gold 标注；留给 P6。 |
| P1 | 新的来源片段语义事件 → 本地 CCEF 1.1 编译器；Scandinavian p319 最新已存真实响应离线重放得到一条 11/11 合法着法的棋谱，包含 `3.Nf3 Bg4 4.d4` 真变例和 8 段锚定说明。 | 仍需提高模型一次输出的稳定性；早期响应分别漏掉变例或注释。 |
| P2 | 错误事件成为局部 unresolved/diagnostic；同局面问题选项去重并保留来源；Catalan p7 的 `9...Nbd7`/`dxe4`/`Na6` 三个选项可合法并列，p9 缺少起始局面的 `16...Nb6` 留作可见疑点。 | Catalan p7–9 全窗口仍只覆盖很小部分；p9 不能凭后续着法猜起始局面。旧 generic repair 尚未从网站 Job 路径退出。 |
| P3 | Makogonov p7 已存响应重放 16/16 合法，同一局面的 `6...c6`/`6...c5` 合为根分支；Endgame p19 图示给 p20 的 36 回合线路提供局面，已存响应重放 18/18 合法，主线与 `36.Kf2`/`38.Ke4` 分支正确。Unicode 棋子符号、无点回合号的 tokenizer/棋步归一化已支持并有聚焦回归。 | Attacking Chess p20 的棋子符号可读，但所选 p19–20 没有可信操作 FEN，不能宣称棋规验证；中文扫描 p20 无嵌入文本，本地未配置 OCR runner，明确停在 `ocr_unavailable`，无法宣称完成中文提取。 |
| P4 | 按页和页内标题／片段长度边界顺序分块，来源 order 本地映射回原页；下一块只收到已验证着法的 ID、SAN、FEN。脚本化跨页主线、分支、独立新局与同页分段通过；Scandinavian p321–322 做了两次真实模型调用；v7 document 追加使用可信前驱锚点并通过聚焦 Job 测试。 | 真实 p321–322 候选中 53 节点仅 38 合法、15 个错误分支节点，37 个片段均有来源表示，另有 2 个 unresolved；这证明跨块续接有效，但不能宣称书籍语义达到可发布质量。单个超长 fragment 仍需更细的断段策略。 |
| P5 | Sources 可选新流程并保留旧版选项；v6/v7 复用 Job、最小 semantic_manifest 迁移、CAS 工件、review 读取及 document 追加。失败 Job 的已提交来源文字可独立读取，来源页图有单独 API/UI。审核修订支持 unresolved→正文／注释／棋谱、初始 FEN 修正、变例重挂。OpenAPI/TS 类型已再生成。 | 已验证端到端脚本化 Job 和审阅读取；生产真实书页端到端仍待 P6 评估。浏览器修订目前使用简明输入框，后续可改善交互。 |
| P6 | 原 21 窗口完成输入预检；三组英文开发窗真实运行，一组中文扫描窗曾确认 `ocr_unavailable`。操作者随后将中文残局书排除出后续测试；当前有效集为六本书、18 窗口、85 页。首轮质量未通过，保留 holdout，详见 `pdf-extraction-p6-acceptance-2026-09-25.md`。 | 有效集的独立人工 gold 尚未完成；需修复英文书的分支语义、双栏/起局等问题，再运行剩余九个开发窗和六个 holdout。中文 OCR 不再是本阶段验收阻碍。 |

关键质量判断：合法着法数量只是一个指标。Scandinavian 的某次响应虽然 16/16 source fragment 都被引用，却把三步正式变例埋在注释里；因此 fragment coverage 不能当完整性证明。局部重挂只在印刷回合号、行棋方与棋规指向唯一既有前驱时执行，并产生 `source_parent_relinked` 诊断；无法唯一判断时保留原错误供审阅。Endgame 的图示 marker 由可信证据生成 figure，模型误把 marker JSON 当标题时不再生成伪正文。

目前新增代码边界：`extraction/draft.py` 提供局部棋谱提示，`interpretation.py` 管短语义请求和原文 quote 定位，`source_compiler.py` 管来源绑定、棋谱结构与 CCEF 编译，`score.py` 只报告缺失不阻止局部成果，`chunks.py` 管顺序分页与上下文。`validation.py` 只做已观察到的记谱字形修正。新流程已接入 Sources；P6 首轮失败后，API 和界面均默认旧版，新流程需显式选择。

验证遵循个人项目的开发要求：聚焦 source compiler、chunk 与观察到的记谱回归；Ruff/MyPy 只检查改动模块。未为每个小改动重复全仓 Stage/覆盖率门禁。P5 持久化时才增加相关 API/数据库测试，P6 收尾再运行适用阶段验收。

P4/P5 聚焦验证：Scandinavian p321–322 真实调用与离线重放保存在忽略目录；新增页内语义边界回归、跨页续接、失败块保留、v6 Job 恢复/审核读取/失败状态来源读取、v7 文档追加、三种人工修订均通过。`make contracts` 与 `make check-contracts` 已运行；空库和既有 SQLite 副本升级 0016 且 `integrity_check=ok`，真实运行库未迁移。未跑全仓门禁或 21 窗口 gold 集，后者属于 P6。
