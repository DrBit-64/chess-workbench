# R3：模型关系协议与程序装配规则（架构草案）

日期：2026-09-26。状态：设计细化，**尚未实现**；不是当前 v6 已支持的 JSON。
所属计划：[R1–R5 开发与验收](pdf-extraction-r1-r5-plan-2026-09-25.md)。
本轮仅设计与文档更新，不修改功能代码，不调用外部模型。

## 1. 四个问题由谁回答

| 问题 | 模型回答 | 程序执行 |
| --- | --- | --- |
| 这一段属于哪一局？ | 根据标题、原文与上下文选择 game_ref；独立示例声明新组 | 管理来源组、起局和引用，检查线路没有跨组连接 |
| 替代哪条线路的黑方第12步？ | 选择 target_line_ref 和确切 target_move_ref | 查到该次来源出现对应的节点，取其父节点作为变化入口 |
| 对应的白方第12步是哪次出现？ | 先选对上述线路及被替代棋步；不能只输出“第12步” | 从选定黑方棋步的前驱取得具体白方节点，核对回合与行棋方 |
| 延续当前变化还是返回外层？ | 选择 line_ref，并指出从该线路的哪次来源棋步继续 | 恢复该线路的节点／棋盘，不接到全局最后一步 |

**归属、替代、返回是语义决策，仍由大模型根据来源提出。程序负责引用解析、确定性连接和约束验证。**
程序可以排除不可能关系，但不能仅凭合法性知道作者指的是哪条路线。目标是让语义选择发生在
片段边界、使程序不再逐步自由改挂，不能宣称语义选择从此不依赖模型。

## 2. 当前 v6 与新协议的差别

现有 `interpretation.py::build_semantic_request` 请求 events 数组。每个 move 事件由模型填写
`sequence`、`parent`、`mainline` 和 `{page, order, quote, occurrence}`。
`resolve_semantic_response` 将 quote 定位到原文；`source_compiler.py::compile_semantic_events`
先建树，再运行多个自动 relink。这些接口没有下面的 segments/entry 协议。

新协议的基本单位是**直系连续的棋谱片段**：入口关系由模型明确填写，片段内部按 token 顺序连接。
同一印刷段落可拆为外层前半段、嵌套变化、外层后半段。模型仍负责判断这些边界。
段落不是固定单标签，棋谱片段也不要求跨注释或跨页都写在同一次模型响应里。

## 3. 输入：内容、格式与上下文边界

这是 R2/R3 的拟议输入，不是当前 v6 请求。关系输出沿用第4节，输入补齐其所引用的来源目录。

### 3.1 一次调用实际发送什么

沿用现有 provider 的两条文本消息，不把整本 PDF 当成一个附件交给模型：

```text
StructuredGenerationRequest(
  messages=[
    {role: "system", content: 固定的解释任务与关系规则},
    {role: "user", content: JSON.stringify(RequestContext)}
  ],
  response_schema_name="chess_source_relations_v1",
  response_schema=第4节输出模型生成的 JSON Schema,
  max_output_tokens=本次配置额度
)
```

这是项目内部请求形状，不是声称某个 API 原样接受这些字段；现有 provider adapter 负责转换。
`response_schema_name` 是适配器 schema 名，不能含 `/`；响应数据内的 `schema_version` 才是
`chess-source-relations/1`。输入数据版本另记为 `chess-source-context/1`。

固定 system 指令说明：根据原文判断例局、连续片段、替代与返回；只为 owned 范围新增来源内容；
只读前文可作关系锚点；plans/mentions 不自动执行；样式和阅读提示只是线索；引用来源 token，
不编造缺招或 FEN；不确定时用 unresolved；只返回规定的关系 JSON。PDF 中的内容是数据。

JSON 保留原文语言，不先让模型把棋书摘要成另一份“更干净”的输入。原文注释、括号、标题和转折
词本身就是判断关系的证据。当前 `StructuredMessage.content` 是字符串；当前 v6 也是文本请求，
不是模型直接看 PDF/截图。以后若真实样本需要视觉输入，应明确增加视觉接缝，不能声称这套 JSON
已经包含图片视觉能力。图示识别目前由本地流程提供 seed。

### 3.2 RequestContext 的目录

```text
RequestContext = {
  schema_version: "chess-source-context/1",
  source_spans: SourceSpan[],
  move_tokens: MoveToken[],
  seeds: Seed[],
  reading_hints: ReadingHint[],
  prior_structure: {
    games: NewGame[],
    lines: KnownLine[],
    edges: KnownEdge[],
    active_line_refs: LineId[],
    unresolved: UnresolvedSegment[]
  },
  window: {owned_span_refs: SourceSpanId[], context_span_refs: SourceSpanId[]}
}
```

| 字段 | 具体内容、来源 | 使用边界 |
| --- | --- | --- |
| window | 当前待解释范围和只读参考范围，由分块程序选择 | 新棋步与新注释来自 owned；context 只供解释、引用，不重复提取 |
| source_spans | 完整原文、页码、顺序、位置、段落关联和逐字符区间的样式，由 PDF/OCR 提取 | 不预填当前段的主线/支线标签；颜色不能压成整行一种 |
| move_tokens | 稳定短 ID、原文中的精确区间、原始 SAN、可辨认的回合号与行棋方，由词法识别产生 | 只表示“这里像着法”；不保证是可执行棋步，也不指定父节点 |
| prior_structure | 相关既有例局、线路入口/接续点、来源父子边、当前嵌套线路和待定关系 | 来自先前解释及人工修订；不是程序凭棋规推导出的正确树 |
| seeds | 标准初始局面及本地已确认的图示起局，附来源 | 提供可引用起点，不能把中途局面默认当成标准初始局面 |
| reading_hints | 自动观察代表性页段得到的简短排版线索及来源例子 | 可为空、可被局部反例修正；不是书名特判或用户模板 |

这里没有新增数据库实体或通用上下文框架，目录由已有证据与当前结构草稿按需组装。

```text
SourceSpan = {
  id: SourceSpanId, fragment_ref: FragmentId,
  page: positive integer, order: nonnegative integer,
  paragraph_ref: string | null,
  bbox: [x0, y0, x1, y1] | null,
  text: string, style_runs: StyleRun[]
}
StyleRun = {
  start: nonnegative integer, end: positive integer,
  font_family: string | null, font_size: number | null,
  bold: boolean | null, color: string | null
}
MoveToken = {
  id: TokenId, span_ref: SourceSpanId,
  start: nonnegative integer, end: positive integer, raw: string,
  move_number: positive integer | null, side: "w" | "b" | null
}
KnownLine = {
  id: LineId, game_ref: GameId,
  entry: Root | AlternativeTo | BranchAfter,
  tip_move_ref: TokenId | null,
  reviewed: boolean
}
KnownEdge = {
  line_ref: LineId, parent_move_ref: TokenId | null, move_ref: TokenId
}
Seed = {
  id: SeedId, kind: "standard" | "diagram" | "continuation",
  source_refs: SourceSpanId[], fen: string
}
ReadingHint = {text: string, source_refs: SourceSpanId[]}
```

坐标原点为页面左上角，bbox 归一化到0–1；page 是1起算的物理页码，order 是页内0起算阅读序号。
字符区间采用 Python Unicode 字符索引 `[start,end)`，不使用 UTF-8 字节或前端 UTF-16 单元；
`raw == span.text[start:end]`。raw 保留原始记谱，不先改成模型猜测的正确 SAN。
同一 SAN 的不同印刷出现有不同 token ID。未印出或无法可靠识别的回合号/行棋方可以为 null；
不能为了填满字段，先假定整个自然段都是一条连续棋谱。括号等未被分词的文本仍在 text 中。

每个 SourceSpan 在该版输入中对应一个完整的来源 fragment，fragment_ref 可供第4节 quote 回退使用；
片段内部变化用 style_runs 和 token 范围表示，跨 fragment 段落用 paragraph_ref 关联。
需要把更细文字范围独立作为注释/证据时，由证据准备阶段保留准确原文映射，不能让模型改写来源。
有嵌入文字的 PDF 从字符属性提取样式；OCR 没有可靠字体时用 null/空 style_runs，不能假造粗体或颜色。
style_runs 按原文顺序排列且互不重叠，尚未获得样式的区间不推断其角色。

KnownLine.entry 记录该线路创建时的入口，tip_move_ref 记录来源线路的接续点，不能退化成
“最近一个棋规合法节点”。active_line_refs 是先前解释留下的相关活动嵌套顺序（外层到内层）。
reviewed=false 明确表示仍为解释草稿；合法性不会把它自动变成人工确认。
KnownEdge 只携带当前判断需要的边，不是完整棋谱树；**缺少一条边表示未随本窗展开，不表示根节点**。
只有显式 parent_move_ref=null 才表示已知根。所传边、入口、接续点及待定项所引用的 token/span
应随该窗提供，避免只给一个模型无法阅读的 ID；不因此递归复制整局全部祖先。

FEN 的生成/合法性验证仍由本地程序负责。模型能读取 seeds 的 FEN，但不需要收到每个节点的
完整 FEN；相关线路的来源路径与明确锚点才是归属判断的主要输入。未知图示不伪装成 Seed，
保留其来源以及缺起点问题；NewGame.seed_ref=null 仍按第4节处理。

### 3.3 与第5节对应的完整输入示例

以下是人为构造的请求，示范同一套 t40/t41/t60/t61/t62/t70 引用如何进入模型。
英文原文、页码、字体与颜色均为协议示例，**不是 Catalan/Magnus 的实际摘录或已验证棋谱 fixture**。
标准 seed 只演示已知起点的传递，不声称示例中省略的前11回合已经提供或验证。
这里用英文说明句让替代与返回关系容易看清；真实输入应保留书里的实际文字，不能人为添加这些提示句。

```json
{
  "schema_version": "chess-source-context/1",
  "source_spans": [
    {
      "id": "s1", "fragment_ref": "f1", "page": 7, "order": 0, "paragraph_ref": "p1", "bbox": [0.1, 0.1, 0.8, 0.13],
      "text": "Example game",
      "style_runs": [
        {"start": 0, "end": 12, "font_family": "Demo Serif", "font_size": 11, "bold": true, "color": "#000000"}
      ]
    },
    {
      "id": "s10", "fragment_ref": "f10", "page": 7, "order": 1, "paragraph_ref": "p10", "bbox": [0.1, 0.2, 0.8, 0.23],
      "text": "12.Re1 Qc8",
      "style_runs": [
        {"start": 0, "end": 10, "font_family": "Demo Serif", "font_size": 11, "bold": true, "color": "#000000"}
      ]
    },
    {
      "id": "s20", "fragment_ref": "f20", "page": 7, "order": 2, "paragraph_ref": "p20", "bbox": [0.1, 0.25, 0.8, 0.28],
      "text": "Instead, 12...Rc8 13.Qd1 Qc7 is another option.",
      "style_runs": [
        {"start": 0, "end": 9, "font_family": "Demo Serif", "font_size": 11, "bold": false, "color": "#000000"},
        {"start": 9, "end": 28, "font_family": "Demo Serif", "font_size": 11, "bold": false, "color": "#0066CC"},
        {"start": 28, "end": 47, "font_family": "Demo Serif", "font_size": 11, "bold": false, "color": "#000000"}
      ]
    },
    {
      "id": "s23", "fragment_ref": "f23", "page": 7, "order": 3, "paragraph_ref": "p23", "bbox": [0.1, 0.3, 0.8, 0.33],
      "text": "In the game: 13.Qd1",
      "style_runs": [
        {"start": 0, "end": 13, "font_family": "Demo Serif", "font_size": 11, "bold": false, "color": "#000000"},
        {"start": 13, "end": 19, "font_family": "Demo Serif", "font_size": 11, "bold": true, "color": "#000000"}
      ]
    }
  ],
  "move_tokens": [
    {"id": "t40", "span_ref": "s10", "start": 3, "end": 6, "raw": "Re1", "move_number": 12, "side": "w"},
    {"id": "t41", "span_ref": "s10", "start": 7, "end": 10, "raw": "Qc8", "move_number": null, "side": null},
    {"id": "t60", "span_ref": "s20", "start": 14, "end": 17, "raw": "Rc8", "move_number": 12, "side": "b"},
    {"id": "t61", "span_ref": "s20", "start": 21, "end": 24, "raw": "Qd1", "move_number": 13, "side": "w"},
    {"id": "t62", "span_ref": "s20", "start": 25, "end": 28, "raw": "Qc7", "move_number": null, "side": null},
    {"id": "t70", "span_ref": "s23", "start": 16, "end": 19, "raw": "Qd1", "move_number": 13, "side": "w"}
  ],
  "seeds": [{"id": "start", "kind": "standard", "source_refs": [], "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"}],
  "reading_hints": [{"text": "In observed spans, bold black score text suggests the played line and blue score text suggests analysis. Prose still determines nesting and returns.", "source_refs": ["s10", "s20", "s23"]}],
  "prior_structure": {
    "games": [{"id": "g1", "kind": "game", "source_refs": ["s1"], "seed_ref": "start"}],
    "lines": [{"id": "main", "game_ref": "g1", "entry": {"kind": "root"}, "tip_move_ref": "t41", "reviewed": false}],
    "edges": [{"line_ref": "main", "parent_move_ref": "t40", "move_ref": "t41"}],
    "active_line_refs": ["main"],
    "unresolved": []
  },
  "window": {"owned_span_refs": ["s20", "s23"], "context_span_refs": ["s1", "s10"]}
}
```

上述数据**没有预先写出 t60 的父节点**。模型利用原文 `Instead`、12... 的回合信息、蓝色样式和
已有 main 的 t40→t41 判断：t60 替代 t41，t61/t62 与其连续；根据 `In the game` 和恢复的样式，
t70 回到 main 的 t41 后。然后返回第5节的两个 segments；程序才计算 t60 的父节点为 t40。
同为 Qd1 的 t61/t70 因来源不同而保持独立。

reading_hints 可由代表页观察先得到，也可复用同一书段已有提示；示例展示已经有提示的情况。
初次调用既有 games/lines/edges/active_line_refs/unresolved 均可为空，reading_hints 也可为空。
模型根据当前原文第一次声明 NewGame 与 root，不能先假设有正确主线再设计输入。

### 3.4 连续阅读范围与本次输出范围分开（后续讨论修订）

操作者指出模型需要大量连续正文，而不仅是若干“相关片段”。此判断有现有失败证据支持。
上一版的字段可以容纳长正文，但“相关前文＋局部补问”不足以保证模型首次就看到了必要语境：
如果程序先按已出错的线路挑少量证据，可能把模型需要用来纠错的内容提前删掉。
因此明确修订为：**优先提供完整、连续的解释范围；每次只输出其中有界的 owned 范围。**

- 阅读范围：预算允许时提供本局/本节在所选提取范围内的完整连续原文，含标题、正文、主谱、
  嵌套分析、问题/答案与恢复主线的后文。不只挑 SAN 邻近句，不只挑“已合法”的节点证据。
- 输出范围：模型为 owned_span_refs 输出新的关系/注释；其余可读正文均为 context_span_refs。
  大阅读范围不要求一次生成同样大的结果，也不退回一次输出整套 CCEF 的旧路径。
- 原文按完整阅读顺序排在 source_spans 数组中，保留段落关联和混合样式；token/关系目录是索引，
  不能替代正文。JSON 容器及片段 ID 不等于每次只给模型读一句话；不需要增加模型生成的摘要层。
- context 可以包括 owned **之前与之后**的文字。后面的回合、变化结束和恢复语句也能帮助判断
  当前段角色；不局限为已经处理过的前文。重复读取只读上下文不重复生成来源棋步。
- 结构目录只是辅助定位，不能覆盖原文。已有语义判断错误时，应保留局部冲突/修正入口，
  而不是要求模型无条件沿用；不能因棋规失败就让该段来源主线从下次输入中消失。

对两个开发样本，首先考虑让 Catalan p6–9 的连续原文全部可读；Magnus p137–149 也先以所选
页段的完整连续原文作为候选阅读范围。实际序列化时核算样式/token 目录、系统指令和预留输出的
总预算，再决定是否拆分；源文字字符数不等于 API token 用量，不在文档里凭页数承诺一定放得下。
本方案不扩大外发授权范围，不为补上下文自动上传其他未授权页面，也不宣称选择的13页等于整本书。

确实过长时，采用有重叠的连续阅读窗口：保留本段前文、后文、当前局标题、较早分支入口原文、
主线进度和各层接续点。优先在段落/章节边界切开；边界未识别时先保留连续邻页，不能假设模型已
解决归属问题后再据此筛选所有输入。只在这些连续原文以外额外加入必要的远处引用证据。
输入预算与本次新增关系的输出预算分别控制，不因输出太多就把阅读范围也缩到一页。

举例（仅说明范围分离，不是默认逐页调用策略；调用粒度见第3.6节）：同一轮可读取 Catalan
p6–9，仅负责输出 p8 的 owned 内容；下一轮仍可读取
p6–9，仅输出 p9。前页目录来自已有解释，后页原文可作 evidence；尚未装配的后页 token 不能假装
已有 node/FEN。如果关系依赖这样的目标，保留依赖直至目标被解释，不能擅自提前执行只读内容。
有跨窗连续片段时，后窗通过明确 continue 与来源锚点续接，不把窗口边界当作分支边界。

仍需保留原先的范围规则：局归属未明时提供相关标题及上下文让模型判断；已传边/入口所引用的
来源锚点可读；短 ID 在同一文档内稳定；最终 node ID、数据库 UUID、hash、UCI 和权威 FEN
由程序维护。模型报告 missing_context 或候选冲突后才做一次有针对性的补读/补问；不把按需补读
当成默认只给极少文字的理由。模型可能自信地选错关系而不报告缺上下文，来源验收仍不可省略。

**范围改进的验收应可观察，而不是仅提高配置上限。** 在保存请求中记录/检查实际可读原文的页段、
字符数、owned 范围和前后文。挑 Catalan p8 的同名 Rc8 变化、Magnus p139–140 的 Bf5 返回等已知
错误点，以相同原文质量、样式、输出协议和编译器，对照窄阅读范围与连续阅读范围的来源父关系；
这样才能判断上下文扩大本身有多少帮助。先做这些有界对照，不为此每次重跑18窗完整验收。
本轮没有调用模型，尚不能宣称长上下文已经使样本通过，也不预设上下文越长准确率必然越高。

### 3.5 相比现有 v6，实际要补什么

当前 `interpretation.py::build_semantic_request` 的 user JSON 是：

```text
{pages, prior_moves, wrapped_moves, numbered_mentions,
 diagram_seeds, choice_hints, move_runs}
```

pages 的每个 fragment 只有 order/text/font_color/bbox，缺少逐字符混合样式与字体粗细；
prior_moves 仍是有限尾部节点提示，没有上述明确线路入口、活动作用域和独立接续点目录。

2026-09-26 只读复核两个 run 的 semantic_manifest，内部 request 均保存 system/user 两条消息；
DeepSeek adapter 实际发送时还前置一条固定 schema system 消息。两者都没有把前面各次调用的
原文作为对话历史重新发送。`generate_semantic_page_chunks` 默认每块最多1页，
还按标题、12000原文字字符及136估算语义单位进一步切分；服务调用没有覆盖这些默认值。
这里的字符/单位上限不是“实际已给模型这么多正文”。实际结果为：

| 历史运行 | 所选页段 | 调用数 | 每次当前块原文字符数 | 当前块是否跨页 |
| --- | --- | --- | --- | --- |
| Catalan | p6–9 | 5 | 690–3087 | 否；p8 分成两块 |
| Magnus | p137–149 | 15 | 17–1891 | 否；p137/p149 各分成两块 |

字符数仅统计 `pages[].fragments[].text`，不含 system/JSON 元数据/词法提示；17字符是一个很小的
独立块，不代表所有 Magnus 正文块都只有17字符。两组原文总量分别为7278和20339字符。
前序信息最多16个合法棋步提示，包含SAN/FEN/来源位置等，不包含对应前页连续正文。
Magnus 从p141起 prior_moves 已无 mainline=true；p145–149 仍使用来自p143–144的节点提示。
因此“当前块含正文”成立，“每轮已看到跨页完整分析”不成立。20次响应均正常 stop，
这些失败不能归因于输出截断；版式丢失、本地误改挂也独立存在，扩大阅读范围不会自动修复它们。

现有词法提示和图示识别可复用，不必为了字段改名重写算法；重构重点是 R2 的证据保真和 R3 的
上下文/关系契约。增加 token 额度不能补回本来没有传入的样式，也不会自动纠正错误的线路摘要。

### 3.6 调用粒度、公共前缀与实际成本（2026-09-26补充，未实现）

**优先按完整讲解段合并输出，确有预算/质量需要才拆；缓存用于降低必要重复读取的成本。**
第3.4节按p8/p9举例是为了说明读/写范围独立，不要求每页一次调用。新协议输出token引用和
片段关系，正文由程序复制，通常比旧CCEF逐项生成负担小。Catalan p6–9可先评估一次生成整段
关系；Magnus按可处理的完整解释段合并为少量调用。是否再拆取决于实测输出/推理用量和来源
关系质量，不预先承诺一次全部正确，也不因某次输出上限耗尽就退回只给单页原文。

这里的四条策略按条件选择，不是固定四轮调用：整段能处理就一次解释；太大才分批；入口仍有
疑点才补问；模型已答对而程序装配错误则只做本地重放。比如Catalan p6–9可先尝试整段关系；
Magnus若确有拆分需要，可分为完整的A/B/C讲解段，三次均能读所需连续正文，但各自只输出一段。
A/B/C仅为调用示意，具体边界以原文为准，不硬写成每页一块。Catalan模型已给b6→cxd5而程序
误改到c6时，保存响应即可验证编译器修复，无需补问模型。独立排版观察等调用仍计入总成本。

#### 官方缓存能力与边界

截至2026-09-26查询，DeepSeek官方上下文缓存默认启用，复用的是已持久化的相同输入前缀。
同一正文放在两份请求的不同中间位置，并不等于能命中。当前指南给出同一长文接不同问题时，
前两次未命中、识别公共前缀后第三次命中的例子；长前缀也可按固定间隔持久化，因此不能保证
第二次就全部命中，也不能把“两次预热”当固定次数规则。缓存为best-effort，闲置后会清理。
这些是官方API的规则，兼容端点或第三方转发的实际缓存/计费须按实际供应商确认。
来源：[DeepSeek Context Caching](https://api-docs.deepseek.com/guides/kv_cache/)。

缓存不是保存并直接返回上一次解析结果。新请求仍要生成本次关系，不能据输入命中推断推理或
输出免费，也不能省略原文改传自行编造的cache ID。仍发送完整相同前缀，服务端按实际命中计费。
来源：[缓存指南](https://api-docs.deepseek.com/guides/kv_cache/)、
[计价规则](https://api-docs.deepseek.com/quick_start/pricing/)。

#### 请求如何组织

上一版JSON示例把变化的window放在source_spans前；这会使公共前缀过早分叉。本轮仅调整
设计示例的顶层字段顺序，含义不变，后续序列化应按以下顺序固定：

```text
固定 schema/system 指令
→ 稳定的 schema_version
→ 同一阅读范围完整的 source_spans（原文、样式、固定来源ID）
→ 同一范围 move_tokens
→ seeds、reading_hints（已知内容；更新仍允许）
→ 本次 prior_structure
→ 本次 window（owned/context范围）
```

最重要的是把大的不变来源放在任何逐轮变化数据之前。短ID、来源阅读顺序、JSON空白与字段顺序
稳定；时间戳/任务随机ID不插在前缀，不因owned变化而重排source_spans或在每段原文中修改角色标记。
输出schema也保持结构稳定，不每页把本次tokenID枚举重新塞入最前面的schema system指令。
修改阅读提示、结构或源证据时正常更新，不能为缓存保留错误内容；source前缀未变的部分仍有复用机会。

需要多次处理同一较长章节时，可以共用一个固定阅读范围，连续完成其中几个owned解释段；
之后再换下一阅读范围。滑窗由p6–9移到p7–10时，重叠页不再是相同起始前缀，不能按重叠字数
估算缓存命中。窗口边界仍以保留语境为先，不为了复用无限附加已无关的整本前文。
不创建专门“请记住这段原文”的付费预热调用；第一个真实任务自然产生缓存候选。

#### 成本统计与降级方案

官方当前Flash价格（美元/百万tokens；截至2026-09-26，实施时需核对）：

| 计费项 | 非高峰 | 高峰 |
| --- | --- | --- |
| 输入，缓存命中 | 0.003 | 0.006 |
| 输入，缓存未命中 | 0.15 | 0.30 |
| 输出 | 0.60 | 1.20 |

仅命中输入部分的单位价为未命中的1/50，不是整个任务便宜98%。例如高峰时重复10万输入tokens，
全部未命中为$0.03，全部命中为$0.0006；这只是该部分输入，排除了动态输入、初次读取及输出费用。
价格与模型别名按[官方定价页](https://api-docs.deepseek.com/quick_start/pricing/)；
不得用旧发布公告的历史价格推算当前账单。

每次调用成本按 `(miss_tokens × miss_price + hit_tokens × hit_price + output_tokens × output_price) / 1e6`
估算，并累计首次失败/重试调用。API的completion_tokens含其reasoning_tokens明细；不要再重复加一次
推理tokens计费，也不要只统计最终JSON长度。API提供prompt_cache_hit_tokens、prompt_cache_miss_tokens
及completion_tokens_details.reasoning_tokens，可直接记录，而不是以文本相似度猜命中。
来源：[Chat Completions usage](https://api-docs.deepseek.com/api/create-chat-completion/)。

当前 `TokenUsage`/DeepSeek成功响应适配只保留 input/output/total 三个计数，没有保留上述缓存和
推理明细；现有semantic_manifest无法证明缓存命中率。后续在现有请求/响应工件中保留供应商已返回
的用量、模型与耗时即可；缺少字段标为未提供，不假定0命中，不先建成本数据库或监控平台。
计费按实际端点、返回模型和调用时费率估算；不得将文档示例当作本项目的已测费用。

缓存效果差或端点没有缓存时，仍按完整解释段合并调用、收紧无关远处上下文、使用连续重叠窗口；
不能退回16个合法节点代替原文。保存响应供本地编译器修改时重放，无需为纯装配bug重调模型；
只有语义协议/输入确实改变或需要新的来源判断时才重新调用。旧响应重放不冒充新协议语义验收。

验收用少量真实任务比较实际hit/miss、总输出/推理、总耗时及来源父关系，不制造额外调用只为刷
缓存命中。缓存未命中只影响成本，不能让来源保留、局部待审或结果正确性依赖供应商缓存存在。

## 4. 最小输出协议

响应数据版本为 `chess-source-relations/1`，provider schema 名为 `chess_source_relations_v1`。以下是具体内部协议草案，实施时由严格 Pydantic
模型生成请求 JSON Schema，不另维护一份较宽松的手写 schema。

```text
Response = {
  schema_version: "chess-source-relations/1",
  games: NewGame[],
  segments: LineSegment[],
  notes: SourceNote[],
  unresolved: UnresolvedSegment[]
}
```

数组均必需，允许为空；对象拒绝未知字段。整窗坏 JSON 退回该窗可信原文；可解析的单条错误
只影响该条及其依赖。这里只做模型输出边界校验，不在每个内部函数重复完整 schema 检查。

### 4.1 NewGame：独立的来源棋谱上下文

```text
NewGame = {
  id: string,
  kind: "game" | "example" | "diagram_line",
  source_refs: SourceSpanId[],
  seed_ref: SeedId | null
}
```

旧来源组不重复声明。新组可以是实战、独立示例或图示题；不是新增一种正式 SQL 实体。
完整走法次序示例另建 example 组，避免与所说明的实战共享主线身份。
seed_ref=null 表示起点未定，结构可读但不能默认套标准初始局面。模型选择标准起点也须与来源
回合相符；只验证棋规仍不能证明起局选择符合作者原意。

### 4.2 LineSegment：一段直系连续棋步

```text
LineSegment = {
  id: string,
  game_ref: GameId,
  line_ref: LineId,
  entry: Root | Continue | AlternativeTo | BranchAfter,
  move_refs: MoveRef[],
  evidence_refs: SourceSpanId[]
}

MoveRef = TokenId | {
  fragment_ref: FragmentId,
  quote: string,
  occurrence: nonnegative integer
}
```

move_refs 非空，按本线路行棋顺序列出；不把嵌套支线棋步混入其中。evidence_refs 指向支撑
分段／关系判断的上下文，而棋步本身的准确位置由 move_refs 提供。引用证据存在不证明解释正确。

通常 MoveRef 直接引用 token。只有词法漏识别时用精确 quote 回退：程序先验证指定 fragment 的
该次 quote 是一个真实来源棋步，再分配 token 引用。不能凭空写 SAN；不能因预分词漏掉 token
就永远无法提取。无法识别仍保留原文，不建设通用全文补写框架。

entry 的四种形式及精确含义：

| 类型 | 字段 | 如何产生首步父节点 |
| --- | --- | --- |
| root | `{"kind":"root"}` | 使用 game_ref 的 seed；父节点为空，建立该组主线 |
| continue | `{"kind":"continue","after_move_ref":"t"}` | 查 line_ref 中的 t；父节点为 node(t)，延续已有线路 |
| alternative_to | `{"kind":"alternative_to","target_line_ref":"L","target_move_ref":"t"}` | 查目标线路中的 t；父节点为 parent(node(t))，新建变化线路 |
| branch_after | `{"kind":"branch_after","target_line_ref":"L","target_move_ref":"t"}` | 查目标线路中的 t；父节点为 node(t)，新建变化线路 |

root/alternative_to/branch_after 的 line_ref 首次定义一条线路；continue 复用已有线路。
一个来源组只有一条 root 主线。alternative_to/branch_after 的 target 必须在同一来源组内，
且确实位于目标线路的来源路径上；不能仅按 SAN 相等认作该节点。

返回外层不使用隐含的“最近主线”指令：输出 continue，明确填外层 line_ref 和 after_move_ref。
Continue 延长该线路已定义的接续点；如果要从更早位置另开分析，则声明新变化。重复印刷用 mention，
不在同一线路再次执行那步棋。多个 segment 的依赖不能互相矛盾或成环；矛盾关系局部待审。

alternative_to 的目标若是根棋步，其父节点为空，仍用同一来源组 seed，不自动重开未知起局。
缺少被替代棋步但知道分出位置时用 branch_after；不能伪造一个 target_move_ref 来凑 alternative_to。

### 4.3 SourceNote 与 UnresolvedSegment

```text
SourceNote = {
  id: string,
  kind: "prose" | "annotation" | "plan" | "mention",
  source_refs: SourceSpanId[],
  anchor: null | {line_ref: LineId, move_ref: TokenId, relation: "before" | "after"}
}

UnresolvedSegment = {
  id: string,
  source_refs: SourceSpanId[],
  move_refs: MoveRef[],
  reason: "missing_context" | "ambiguous_relation" | "unparsed_notation",
  candidates: {game_ref: GameId, line_ref: LineId, entry: Entry}[]
}
```

note 原文由程序复制。plan/mention 不执行其中的着法；mention 必须指向已知来源棋步。
混合的计划与连续变化应各自绑定对应来源片段。模型误判也应能纠正，不能把非法棋谱一概降成 plan。

unresolved 不确定时保留候选，候选可为空；程序不默认取第一项，也不自动另建标准起局。
这里的候选只是若干入口提议，不要求模型同时输出多棵完整棋谱树或 FEN。

## 5. 12...Rc8：具体请求上下文与输出

以下短 ID 是协议演示，**不是实际模型响应或通过棋规验证的完整 fixture**。
输入已有 game g1 与主线 main，且已知：

| Token ID | 对应的来源出现 |
| --- | --- |
| t40 | 实战主线的 `12.Re1` |
| t41 | 实战主线的 `12...Qc8`，其父节点对应 t40 |
| t60、t61、t62 | 分析里的 `12...Rc8 13.Qd1 Qc7` |
| t70 | 分析结束后，实战正文里的 `13.Qd1` |
| s20、s23 | 支撑“另一个黑方应手”“回到实战”的上下文 spans |

模型的完整响应示例：

```json
{
  "schema_version": "chess-source-relations/1",
  "games": [],
  "segments": [
    {
      "id": "seg_rc8",
      "game_ref": "g1",
      "line_ref": "line_rc8",
      "entry": {
        "kind": "alternative_to",
        "target_line_ref": "main",
        "target_move_ref": "t41"
      },
      "move_refs": ["t60", "t61", "t62"],
      "evidence_refs": ["s20"]
    },
    {
      "id": "seg_resume",
      "game_ref": "g1",
      "line_ref": "main",
      "entry": {
        "kind": "continue",
        "after_move_ref": "t41"
      },
      "move_refs": ["t70"],
      "evidence_refs": ["s23"]
    }
  ],
  "notes": [],
  "unresolved": []
}
```

模型已经作出的选择是：g1、main 的 t41 被替代、新变化叫 line_rc8、t60..t62 连续，
以及 t70 恢复 main 的 t41 之后。**这些选择不是程序从棋规推导出来的。**

程序必须计算：

```text
parent(Rc8@t60) = parent(Qc8@t41) = Re1@t40
parent(Qd1@t61) = Rc8@t60
parent(Qc7@t62) = Qd1@t61
parent(Qd1@t70) = Qc8@t41
```

t61 与 t70 同为 Qd1，但不是同一次来源出现，不能合并或互相续接。
如果还有嵌套变化，就再声明一条 variation 线路，其入口引用 line_rc8 的具体 token；
后文恢复 line_rc8 时用 continue 指明中断前的接续点，机制不需要增加新的操作种类。

## 6. 程序如何处理输出

1. **解码并绑定来源。** 在模型边界验证 shape、引用与 owned 范围，精确定位 quote 回退。
   错误条目保留真实来源为待审，不让模型生成的文字取代证据。
2. **登记结构草稿。** 注册来源组和线路、建立 segment 依赖，按依赖顺序装配。
   原书阅读顺序按来源位置独立保存，不能用装配顺序覆盖。
3. **解析片段入口。** root 用 seed；continue/branch_after 取目标节点；alternative_to 取目标父节点。
   目标来源节点存在但其局面未知时保留依赖，不能跳到无关的合法节点。
4. **建立连续父子关系。** 对片段 m1..mn，入口父节点 P：parent(m1)=P；parent(mi)=m(i-1)，i>1。
   程序按来源 SAN 重放，核对回合号／行棋方，计算 UCI 和前后 FEN；嵌套分支用各自入口棋盘。
5. **处理局部冲突。** 保留可用前缀、原文与问题，阻断受影响后代的棋规确定状态。
   不能悄悄修改模型已声明的入口，更不能用过期 FEN 继续改挂。入口修正后重算受影响子树。
6. **生成 CCEF 审核候选。** 程序生成 node ID、引用、注释与 reading_flow，保留来源关系映射。
   继续经过现有人工审核与发布边界，不直接写正式知识库。

上述“验证通过”只表示引用存在、结构约束成立、棋规一致。
它不会自动证明模型选中了作者真正讨论的线路，也不因为 evidence_refs 非空就认定有充分语义证据。

## 7. 多候选如何处理

正常路径中模型直接给出具体关系，程序查表／计算，不做全图父节点搜索。
模型报告歧义、缺上下文或所选关系发生冲突时，才处理候选：

- 取模型指出的来源组、相关当前／上层／被文字引用线路，查其中符合回合和行棋方的位置；
  必要时补读该范围的来源上下文。缺局名或线路归属本身仍需模型解释，程序不能自行假定。
- 用来源作用域与整段棋规排除明显不可能项。不存在候选时保留 missing_context，不能扩大为
  “全书哪个局面能走就挂哪个”的搜索，也不能补造缺失应招。
- 首轮输出已经明确且约束相符，无需再次调用。多个合理候选可以只补问一次局部关系，
  输入候选 ID、原文／样式与相关路径，返回选择或 unresolved。
- 即使只剩一个合法候选，也须符合来源关系；唯一合法不是语义正确性的证明。
  模型自报 confidence、解释篇幅和“多数候选已淘汰”均不能代替来源核对。

有限补问无法保证所有书都自动处理正确。仍有疑点时只留下该分支根问题，不把每个后代变成独立人工任务。

## 8. 改造接缝与验收

| 文件 | 后续职责 |
| --- | --- |
| `extraction/draft.py` 或实际需要的小型内部模型模块 | Token、Game、Line、Segment 与 Entry 的类型，保持来源映射 |
| `extraction/interpretation.py` | 组装来源目录与上下文；生成严格关系 schema；解码模型选择 |
| `extraction/chunks.py` | 维护来源线路进度与依赖，提供相关前文；不只传末16合法节点 |
| `extraction/source_compiler.py` | 入口公式、连续装配、局部问题和 CCEF 编译；不再由多个全局 relink 覆写明确关系 |
| `extraction/score.py` 与评估脚本 | 对照来源的主线、分支入口、遗漏及待审负担，而非只统计合法率 |

这是新解释协议，不能只把它转换为旧 events 后继续跑原来的自由改挂链。
可复用纯棋规规范化和 CCEF 打包；保留旧版本响应读取，标明新协议/工件版本，不重写历史基线。
架构仍是少量类型、普通函数和顺序 worker，不新增通用推理／工作流框架。

先验证“替代一个黑方应手→恢复主线”的具体父关系，再用一个嵌套变化与同 SAN 不同来源例子核对。
真实验收用 Catalan p7/p8 与 Magnus p139/p140 的原文标注；至少包含一个错误父节点仍然合法的案例，
防止验收退化为仅验证 python-chess。协议示例仅做文档结构检查，不冒充真实棋谱回归。
