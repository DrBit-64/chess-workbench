# ChessWorkbench 项目描述

> 一个面向个人长期学习的国际象棋知识整理、交互训练、实战复盘与 AI 辅助内容导入平台。

- 项目名称：**ChessWorkbench**
- 仓库名：`chess-workbench`
- 文档用途：作为 Codex 和开发者理解项目目标、范围、界面、数据模型与技术路线的主项目说明。
- 当前阶段：项目初始化与 MVP 设计。
- 开发定位：首先是单用户、本地优先的个人工具；架构上保留后续多用户部署与实时协作的扩展空间。
- 学习目标：在完成国际象棋工具的同时，积累能够迁移到合作网站项目中的 React、Sanic、SWR、Ant Design、SQLAlchemy、WebSocket、Yjs、LMDB、Docker 和 Nginx 经验。

---

## 1. 项目背景

用户已经拥有大量国际象棋棋书、扫描版 PDF、视频课程和个人实战对局，但这些资料目前主要是线性、静态且分散的：

- 棋书中的变化和说明难以在棋盘上交互查看；
- 视频中的理论难以整理成可检索、可复习的内容；
- Lichess Study 在分支很多时容易变得拥挤；
- 开局资料来自多个作者时，推荐可能相同、互补或冲突；
- 理论知识与个人实战中的真实错误之间缺乏连接；
- 现有网站往往分别解决开局训练、残局训练、引擎分析或对局复盘，而不是形成统一的个人知识系统；
- “标准答案”不能简单等同于单一引擎最佳着，因为个人开局库、客观可行着、残局定式和教学目标使用不同的判定标准。

本项目希望把这些资料统一转换为一种以**局面、着法、来源、解释、个人选择和练习记录**为核心的数据系统，并提供交互棋盘、练习、引擎和实战分析功能。

---

## 2. 核心设计原则

### 2.1 资料来源、知识、个人选择和训练题必须分离

系统中需要明确区分：

1. **Source（资料来源）**
   - 一本棋书的一章；
   - 一个 PDF 页段；
   - 一段视频；
   - 一篇网页文章；
   - 一份 PGN；
   - 一盘个人实战。

2. **Knowledge（知识内容）**
   - 某个局面的候选着；
   - 某条变化；
   - 计划、原则和解释；
   - 作者观点；
   - 典型错误；
   - 示例对局；
   - 残局定式。

3. **Personal Repertoire（个人开局库）**
   - 用户在实战中准备使用的首选着法；
   - 可接受替代；
   - 暂不训练的变化；
   - 明确避免的变化。

4. **Exercise（练习题）**
   - 从某个局面开始；
   - 有指定的题型和判题策略；
   - 记录独立的复习状态；
   - 可以来自理论资料，也可以来自个人对局错误。

不同资料可以对同一局面给出不同观点。系统不能在导入时强行覆盖，而应保存来源并在审核后合并到知识层。

### 2.2 内部结构以局面图为核心，而不是单棵 PGN 树

国际象棋开局存在大量转置，因此内部模型应采用局面图：

```text
Position A
├── Move 1 → Position B
├── Move 2 → Position C
└── Move 3 → Position D

Position X
└── Move 4 → Position C
```

多个着法顺序可以指向同一局面节点。PGN 用于导入和导出，但不是唯一的内部存储格式。

### 2.3 AI 只生成候选结果，不能成为棋谱正确性的唯一来源

AI 适合：

- OCR 后文字清理；
- 章节结构识别；
- 棋谱与注释关联；
- 多来源观点摘要；
- 视频转录与局面对齐；
- 错误类型解释；
- 生成初始练习建议。

AI 输出必须经过：

1. JSON Schema 校验；
2. 棋规合法性验证；
3. 前后局面一致性检查；
4. 引擎或残局表库辅助检查；
5. 人工审核。

### 2.4 引擎是检查器和分析工具，不是唯一课程作者

系统需要区分：

- 用户个人开局库中的首选着；
- 客观可接受着；
- 引擎近似等价着；
- 明显不推荐着；
- 教学中必须掌握的关键着；
- 理论残局中保持胜、和或完成定式的着法。

### 2.5 默认只展示当前需要的复杂度

大量分支不应默认以完整巨型树展示。主要学习界面采用局部展开：

- 棋盘显示当前局面；
- 右侧只显示当前节点的直接候选着；
- 顶部显示当前路径；
- 左侧显示课程目录和关键局面；
- 完整图仅作为高级导航与编辑视图。

---

## 3. 功能需求

### 3.1 整理棋书和视频理论

用户能够：

- 新建课程、模块和章节；
- 从任意 FEN 或 PGN 开始；
- 在棋盘上建立主线和分支；
- 给局面、着法和变化添加说明；
- 记录计划、候选着、常见错误和关键原则；
- 给内容关联一个或多个资料来源；
- 保存 PDF 页码、截图区域和视频时间戳；
- 查看同一局面下不同来源的观点；
- 将其中一条路线选入个人开局库。

### 3.2 训练开局谱与残局定式

用户能够：

- 按课程、分支或个人开局库生成练习；
- 使用间隔重复安排复习；
- 练习开局着法回忆；
- 练习多个可接受候选着；
- 练习定式关键步；
- 从残局局面开始把局面下完；
- 依据引擎或 Syzygy 判断结果；
- 查看错误原因和来源解释；
- 从个人对局中自动生成复习题。

### 3.3 从指定局面继续下棋

用户能够：

- 从课程、开局库、残局或实战中的任意节点开始；
- 选择执白或执黑；
- 与 Stockfish 对弈；
- 调整引擎强度；
- 限制引擎时间和资源；
- 对局结束后查看关键错误；
- 将新发现的局面保存到课程或练习库。

### 3.4 引擎分析

用户能够：

- 查看当前局面分数；
- 查看 MultiPV 候选线；
- 查看 WDL；
- 配置分析时间、节点数、线程和 Hash；
- 执行实时浅分析；
- 执行后台深度分析；
- 缓存相同局面的结果；
- 对七子及以下残局优先查询表库；
- 查看引擎版本和分析参数。

### 3.5 导入 Lichess 对局并提取典型错误

用户能够：

- 输入或连接 Lichess 用户名；
- 按日期、时间控制、颜色和开局筛选对局；
- 幂等导入 PGN；
- 执行后台分析；
- 找到个人开局库中的首次偏离；
- 区分“偏离个人主线”和“客观错误”；
- 将错误匹配到已有开局模块；
- 将残局错误匹配到残局类型或定式；
- 聚类重复出现的错误；
- 自动生成针对性练习；
- 查看某个课程相关的所有个人对局；
- 查看某类错误的复发次数和改善趋势。

### 3.6 AI 辅助导入棋书和视频

用户能够：

- 上传 PDF；
- 选择页码范围；
- 对扫描件执行 OCR；
- 识别正文、棋谱区块和棋盘图；
- 将章节转换为结构化候选内容；
- 审核低置信度结果；
- 将合法分支导入知识图；
- 上传或指定视频文件；
- 提取音频和关键帧；
- 转录解说；
- 识别棋盘状态变化；
- 将讲解与局面对齐；
- 将内容转换为课程、说明和练习草稿。

---

## 4. 信息架构

主界面分为五个一级区域。

### 4.1 学习 Learn

用于浏览按主题组织的课程内容。

示例：

```text
开局
├── 斯堪的纳维亚防御
│   ├── 2...Nf6
│   │   ├── 早期 Nf3：何时用马回吃
│   │   ├── 早期 Nf3：何时用后回吃
│   │   ├── 冰岛弃兵
│   │   └── 葡萄牙弃兵
│   └── 2...Qxd5
└── 斯拉夫防御
    ├── Ne5 主变
    ├── 交换变例
    └── 典型中局结构

残局
├── 车兵残局定式
├── 后兵残局
├── 轻子残局
└── 少子复杂残局
```

课程按问题和决策点组织，不按“书 A 第三章”或“视频 B 第七集”组织。

### 4.2 个人开局库 Repertoire

只保存用户准备在实战中采用的路线。

每个局面可以标记：

- `preferred`：首选着法；
- `accepted`：可接受替代；
- `inactive`：保留但暂不训练；
- `avoid`：明确避免；
- `unreviewed`：尚未决定。

### 4.3 练习 Practice

包括：

- 今日复习；
- 开局回忆；
- 残局定式；
- 从局面继续下；
- 个人错误重练；
- 新导入资料的待掌握局面；
- 自定义练习集；
- 复习统计。

### 4.4 我的对局 Games

包括：

- Lichess 对局列表；
- 单盘分析；
- 开局偏离；
- 关键错误；
- 错误聚类；
- 关联课程；
- 关联残局；
- 自动生成练习；
- 按时间查看进步。

### 4.5 资料 Sources

包括：

- PDF；
- 视频；
- PGN；
- 网页笔记；
- 手工录入来源；
- AI 导入任务；
- OCR 结果；
- 审核状态；
- 与现有知识的冲突；
- 来源引用位置。

---

## 5. 界面设计构想

## 5.1 首页 / Dashboard

首页展示当前最有行动价值的信息：

- 今日待复习数量；
- 最近学习的课程；
- 待审核 AI 导入任务；
- 最近导入的 Lichess 对局；
- 高频重复错误；
- 当前个人开局库覆盖率；
- 后台任务进度；
- 快速入口：
  - 新建课程；
  - 导入 PGN；
  - 导入 PDF；
  - 导入视频；
  - 同步 Lichess；
  - 从 FEN 开始分析。

首页可以使用 Ant Design 的卡片、统计数值、列表和进度组件。

## 5.2 课程列表页

页面形式可以类似 Lichess Study 列表，但增加更多元数据和筛选。

每个课程卡片显示：

- 标题；
- 类型：开局、残局、中局、战术；
- 当前进度；
- 章节数；
- 关键局面数；
- 来源数；
- 待复习题数；
- 关联个人对局数；
- 最后编辑时间；
- 标签；
- 是否属于个人开局库。

支持：

- 搜索；
- 按类型筛选；
- 按标签筛选；
- 按最近学习排序；
- 按错误关联数量排序；
- 文件夹或集合；
- 列表视图和卡片视图。

## 5.3 单个课程页面

推荐布局：

```text
┌──────────────────────────────────────────────────────────┐
│ 面包屑 / 当前路径 / 课程工具栏                            │
├──────────────┬───────────────────────┬───────────────────┤
│ 章节目录     │       交互棋盘        │ 当前候选着与分支  │
│ 关键局面     │                       │                   │
│ 搜索与标签   │                       │                   │
├──────────────┴───────────────────────┴───────────────────┤
│ Tabs：说明｜来源｜引擎｜我的对局｜练习｜历史版本          │
└──────────────────────────────────────────────────────────┘
```

### 左栏：章节和局面导航

显示：

- 课程目录；
- 当前模块；
- 关键局面列表；
- 收藏局面；
- 待审核节点；
- 个人错误节点；
- 搜索结果。

### 中栏：棋盘

支持：

- 拖动和点击走棋；
- 棋盘翻转；
- 上一步着法高亮；
- 候选着箭头；
- 自定义箭头和格子着色；
- 设置起始局面；
- 返回分支父节点；
- 与引擎继续下；
- 开始练习；
- 复制 FEN；
- 导出当前线 PGN。

### 右栏：局部分支列表

默认只显示当前局面的直接候选着。

每条着法可显示：

- SAN；
- 角色：个人首选、可接受、理论分支、错误着；
- 引擎评价；
- 来源数量；
- 个人实战次数；
- 个人错误率；
- 是否有说明；
- 是否存在转置；
- 后继模块名称。

### 下方 Tabs

#### 说明

- 当前局面的核心问题；
- 计划；
- 候选着比较；
- 常见错误；
- 记忆提示；
- Markdown 注释。

#### 来源

显示每个来源的独立观点，并保留页码或视频时间。

#### 引擎

- 当前评分；
- WDL；
- MultiPV；
- 分析深度、节点和版本；
- 启动实时分析；
- 提交后台深度分析；
- 加入候选着；
- 比较两条路线。

#### 我的对局

- 到达过该局面的对局；
- 实际选择；
- 后续结果；
- 首次偏离；
- 重复错误；
- 链接到单盘复盘。

#### 练习

- 关联练习；
- 下一复习时间；
- 正确率；
- 最近错误；
- 创建新练习；
- 立即练习。

#### 历史版本

- 注释修改；
- 个人开局选择变化；
- AI 导入合并记录；
- 答案策略版本；
- 引擎评价更新。

## 5.4 全局图视图

全局图不是默认学习界面，而是用于：

- 检查课程结构；
- 查看转置；
- 检查孤立节点；
- 批量编辑节点；
- 审核 AI 导入；
- 查看模块关系。

支持：

- 折叠子树；
- 只显示指定深度；
- 只显示个人开局库；
- 只显示某个来源；
- 只显示个人错误节点；
- 跳转到局部课程界面。

React Flow 可作为后期实现，不是 MVP 阻塞项。

## 5.5 练习页面

```text
┌─────────────────────────────────────┐
│ 练习类型 / 进度 / 退出              │
├───────────────────┬─────────────────┤
│      棋盘         │ 提示与结果      │
│                   │                 │
├───────────────────┴─────────────────┤
│ 答案解释 / 来源 / 下次复习          │
└─────────────────────────────────────┘
```

支持题型：

1. `exact`
2. `repertoire`
3. `accepted-set`
4. `engine-threshold`
5. `tablebase`
6. `play-out`

答题反馈区分：

- 个人主线；
- 合理替代；
- 可行但不在个人开局库；
- 课程中不推荐；
- 客观错误；
- 未知，需要审核。

## 5.6 对局复盘页

```text
┌───────────────┬────────────────────┬────────────────────┐
│ 对局信息      │       棋盘         │ 着法与引擎评价     │
│ 开局与标签    │                    │                    │
├───────────────┴────────────────────┴────────────────────┤
│ 错误解释｜关联课程｜生成练习｜相似错误                  │
└─────────────────────────────────────────────────────────┘
```

## 5.7 AI 导入审核页

```text
┌──────────────────┬──────────────────┬────────────────────┐
│ 原始 PDF/视频    │      棋盘        │ 结构化候选结果     │
│ 页图/时间轴      │                  │ 变化、说明、警告   │
└──────────────────┴──────────────────┴────────────────────┘
```

需要高亮：

- OCR 低置信度文本；
- 非法着法；
- 无法确定的棋盘方向；
- 无法连接的变化；
- AI 推断内容；
- 与现有知识冲突的推荐；
- 可合并的相同局面；
- 可能的转置。

---

## 6. 多来源内容组织策略

### 6.1 导入阶段按来源分开

每个来源独立保存，并具有独立抽取结果和审核状态。

### 6.2 正式知识按局面合并

- 不同推荐并存；
- 相同推荐合并来源；
- 不同解释并存；
- 冲突显式展示；
- 转置指向相同 Position；
- 用户手工决定个人开局选择。

### 6.3 课程按问题组织

课程围绕决策点、计划和典型局面，而不是来源目录。

---

## 7. “标准答案”设计

系统不能只有一个全局标准答案。

### 7.1 个人开局答案

结果分类：

- 首选着；
- 可接受替代；
- 合理但偏离个人库；
- 不推荐；
- 错误。

### 7.2 人工审核的可接受着集合

```json
{
  "preferredMoves": ["g8f6"],
  "acceptedMoves": ["d8d5"],
  "discouragedMoves": ["c8g4"]
}
```

### 7.3 引擎阈值

非唯一解局面可以设置允许的评价损失，并记录引擎版本和参数。

### 7.4 残局结果判定

使用 WDL、DTZ、是否维持胜势或和势，以及是否完成指定定式。

### 7.5 版本化

每个练习记录：

- 课程版本；
- 个人开局库版本；
- 答案策略版本；
- 引擎版本；
- 来源审核状态。

---

## 8. Lichess 对局分析与错误匹配

### 8.1 导入

- 通过 Lichess API 导入用户对局；
- 以 Lichess game ID 幂等保存；
- 保存 PGN、时间控制、颜色、结果、日期、开局和时钟数据；
- 后台执行引擎分析。

### 8.2 局面匹配

优先级：

1. 精确 `position_key`；
2. 转置后的相同局面；
3. 最近共同课程节点；
4. ECO 和着法前缀；
5. 兵型、材料和标签；
6. 残局材料签名与定式特征。

### 8.3 错误分类

- `repertoire_deviation`
- `theoretical_mistake`
- `conceptual_mistake`
- `tactical_oversight`
- `endgame_technique_failure`
- `time_management`
- `unknown`

### 8.4 典型错误优先级

```text
训练价值 =
    重复出现程度
  × 与现有课程匹配程度
  × 客观损失
  × 可解释性
  × 可复现性
```

---

## 9. AI 文档与视频导入流程

### 9.1 PDF

```text
上传 PDF
→ 文件哈希与存储
→ OCRmyPDF 预处理
→ PyMuPDF 页面渲染
→ PaddleOCR 版面与文字识别
→ AI 识别章节、正文、棋谱、棋盘图和说明
→ 输出结构化候选 JSON
→ python-chess 合法性验证
→ 与棋盘图和后续局面交叉验证
→ 人工审核
→ 合并到知识图
```

### 9.2 视频

```text
上传视频
→ FFmpeg 提取音频
→ 语音转录与时间戳
→ 场景变化和棋盘区域检测
→ 提取棋盘变化关键帧
→ 识别连续局面
→ 利用合法着法约束连接局面
→ 将转录与局面对齐
→ AI 生成变化、说明和练习候选
→ 人工审核
→ 合并到知识图
```

### 9.3 AI Provider 抽象

支持：

```text
AI_PROVIDER=mock
AI_PROVIDER=openai
```

模型调用通过统一接口，输出使用 Pydantic Schema 校验。

---

## 10. 核心领域模型

### Position

- `id`
- `fen`
- `position_key`
- `side_to_move`
- `piece_placement`
- `castling_rights`
- `en_passant`
- `material_signature`
- `created_at`

### MoveEdge

- `id`
- `from_position_id`
- `to_position_id`
- `uci`
- `san`
- `nag`
- `sort_order`
- `created_at`

### Source

- `id`
- `type`
- `title`
- `author`
- `file_path`
- `file_hash`
- `external_url`
- `metadata_json`
- `status`
- `created_at`

### SourceSpan

- `source_id`
- `page_number`
- `bbox`
- `video_start`
- `video_end`
- `quote`
- `ocr_text`
- `confidence`

### Course

- `id`
- `title`
- `description`
- `category`
- `tags`
- `status`
- `version`

### CourseModule

- `id`
- `course_id`
- `parent_id`
- `title`
- `description`
- `start_position_id`
- `sort_order`

### KnowledgeNote

- `id`
- `target_type`
- `target_id`
- `note_type`
- `markdown`
- `source_span_id`
- `review_status`
- `version`

### Repertoire / RepertoireChoice

保存个人首选着、可接受替代、暂不训练和避免变化。

### Exercise / ReviewCard

保存题型、答案策略、提示、解释、来源与 FSRS 状态。

### Game / GamePosition / GameError

保存 Lichess 对局、每一步局面、评价、错误分类和课程关联。

### EngineAnalysis

保存引擎版本、参数、MultiPV、WDL 和缓存结果。

### ImportJob

保存任务类型、状态、进度、结果、错误和取消请求。

---

## 11. 技术栈选择

本项目刻意与合作开发项目保持较高一致，以便开发经验可迁移，但不复制其 reducer、ZeroMQ、完整状态镜像和 Remote ESM 架构。

### 11.1 总体架构

```text
TypeScript + React SPA
        │ HTTP / WebSocket
        ▼
Python + Sanic API
        │
        ├── Application Services ──→ SQL 数据库
        ├── Background Jobs ───────→ Stockfish / OCR / AI / FFmpeg
        └── Collaboration Later ───→ Yjs / pycrdt / LMDB

Nginx
├── React 静态文件
├── Sanic API
├── WebSocket
└── Yjs Syncer（后期）

Docker Compose
├── nginx
├── api
├── worker
├── mysql
└── syncer（后期）
```

### 11.2 前端

- TypeScript 5.9
- React 18
- Vite 7
- React Router 7
- SWR 2
- Ant Design 6
- Tailwind CSS 4
- CSS Modules
- React Context
- `useReducer`
- `useState`
- `react-chessboard`
- `chess.js`
- React Flow（后期可选）

分工：

- SWR：正式服务器数据；
- Context：设置、主题、引擎配置；
- `useReducer`：棋谱编辑会话与 undo/redo；
- `useState`：局部 UI；
- AntD：复杂控件；
- Tailwind：布局；
- CSS Modules：棋盘与专用交互。

### 11.3 后端

- Python 3.13
- Sanic
- sanic-ext
- Pydantic 2
- SQLAlchemy 2
- Alembic
- SQLite
- MySQL/MariaDB
- PyMySQL
- httpx
- python-chess
- 独立数据库任务 worker

数据库路线：

1. MVP 使用 SQLite；
2. 基本功能稳定后增加 MySQL 集成环境；
3. 正式部署默认使用 MySQL 兼容数据库；
4. 不依赖 SQLite 特有行为。

### 11.4 Stockfish

- 原生 Stockfish；
- 后端 UCI 子进程；
- 实时浅分析；
- 后台深度分析；
- 结果缓存；
- Syzygy。

默认实时配置：

```text
Threads = 1
Hash = 128 MB
MultiPV = 3
movetime = 300–800 ms
Ponder = false
```

### 11.5 后台任务与 WebSocket

第一阶段采用 SQL 任务表和独立 Python worker，不使用 Celery、Redis 或 ZeroMQ。

WebSocket 只发送轻量通知，前端收到后调用 SWR `mutate` 获取正式数据。

### 11.6 间隔重复

- FSRS
- Python 端实现

相同局面可以生成多个独立练习，并拥有独立复习状态。

### 11.7 PDF、OCR 与视频

- PyMuPDF
- OCRmyPDF
- PaddleOCR
- FFmpeg
- OpenAI transcription API
- 后续可增加本地 Whisper

### 11.8 大模型

- OpenAI Responses API
- Structured Outputs
- Pydantic JSON Schema
- Provider 抽象
- Mock Provider

应用没有 API key 时仍可运行非 AI 功能。

### 11.9 实时协作（后期）

- Yjs
- y-websocket 兼容协议
- pycrdt
- LMDB
- awareness

Yjs 只管理协作草稿和临时状态；正式课程、开局库、训练记录和分析结果保存在 SQL 中。

### 11.10 部署

- Nginx
- Docker
- Docker Compose
- GitHub Actions

Nginx 路由：

```text
/          → React 静态文件
/api/      → Sanic API
/ws/       → Sanic WebSocket
/sync/     → Yjs Syncer（后期）
```

---

## 12. 明确不采用的架构

第一阶段不采用：

- Next.js
- Redux
- Zustand
- TanStack Query
- TanStack Router
- FastAPI
- GraphQL
- PostgreSQL
- Redis
- Celery
- ZeroMQ
- reducer 权威写入进程
- 每个 worker 的完整内存状态镜像
- Neo4j
- Elasticsearch
- 向量数据库
- Remote ESM
- 后端下发任意前端脚本
- 全自动整书无审核导入

---

## 13. 安全与一致性要求

### API 契约

- Pydantic 定义服务端 Schema；
- 由 OpenAPI 生成 TypeScript 类型；
- 前端不手写重复 DTO；
- 关键接口可增加 Zod 运行时验证；
- CI 检查生成文件同步。

### 富文本

- Markdown 保存；
- 渲染后清理 HTML；
- 不执行资料中的脚本；
- 不允许任意 Remote Component；
- 练习类型通过内部注册组件渲染。

### 文件

- 内容哈希命名；
- SQL 只保存相对路径和元数据；
- 大型 PDF、视频和帧图不存为 BLOB；
- 上传限制大小和 MIME；
- 原始文件与衍生文件分离。

### 构建

- 干净 checkout 可复现；
- 不依赖 Git 忽略但构建必需的源码；
- `.env.example` 完整；
- migration 可从空库执行；
- Docker 镜像可独立构建。

---

## 14. 推荐仓库结构

```text
chess-workbench/
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── routes/
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── board/
│   │   │   ├── courses/
│   │   │   ├── repertoire/
│   │   │   ├── practice/
│   │   │   ├── games/
│   │   │   ├── sources/
│   │   │   ├── engine/
│   │   │   └── collaboration/
│   │   ├── logic/
│   │   │   ├── api/
│   │   │   ├── swr/
│   │   │   ├── websocket/
│   │   │   └── editor/
│   │   ├── contexts/
│   │   ├── types/
│   │   └── styles/
│   ├── package.json
│   └── vite.config.ts
│
├── backend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── app.py
│   │   │   ├── endpoint/
│   │   │   ├── middleware/
│   │   │   └── websocket/
│   │   ├── domain/
│   │   │   ├── positions/
│   │   │   ├── courses/
│   │   │   ├── repertoire/
│   │   │   ├── exercises/
│   │   │   ├── games/
│   │   │   └── sources/
│   │   ├── store/
│   │   ├── schemas/
│   │   ├── logic/
│   │   │   ├── engine/
│   │   │   ├── jobs/
│   │   │   ├── ingestion/
│   │   │   └── analysis/
│   │   ├── integrations/
│   │   │   ├── lichess/
│   │   │   └── openai/
│   │   └── sync/
│   ├── migrations/
│   ├── tests/
│   └── pyproject.toml
│
├── data/
│   ├── sources/
│   ├── derived/
│   ├── engines/
│   ├── tablebases/
│   └── database/
│
├── docs/
│   ├── project-description.md
│   ├── architecture.md
│   ├── domain-model.md
│   ├── data-format.md
│   └── adr/
│
├── scripts/
├── docker/
├── docker-compose.yml
├── Dockerfile
├── pnpm-workspace.yaml
├── .env.example
├── Makefile
└── README.md
```

---

## 15. 分阶段开发计划

### Phase 0：项目初始化

- 建立前后端目录；
- React/Vite/Sanic 可启动；
- SQLite 可连接；
- CI 执行静态检查和测试；
- OpenAPI 可生成前端类型；
- 建立架构文档。

### Phase 1：局面图与手工课程编辑 MVP

- Position；
- MoveEdge；
- Source；
- Course；
- CourseModule；
- KnowledgeNote；
- PGN 导入与导出；
- FEN 导入；
- 棋盘页面；
- 局部分支列表；
- Markdown 注释；
- 课程列表；
- 后端合法性验证；
- PGN round-trip 测试。

### Phase 2：个人开局库与练习

- Repertoire；
- RepertoireChoice；
- Exercise；
- 答案策略；
- FSRS；
- 今日复习；
- 开局回忆题；
- 残局题；
- 从局面继续下。

### Phase 3：Stockfish 与后台任务

- 原生 Stockfish；
- 实时浅分析；
- 后台深度分析；
- job 表；
- worker；
- WebSocket 通知；
- SWR 失效；
- 引擎缓存；
- 与引擎对弈。

### Phase 4：Lichess 对局

- Lichess API；
- 对局导入；
- 幂等写入；
- 单盘分析；
- 个人开局偏离；
- GameError；
- 错误聚类；
- 课程匹配；
- 从错误生成练习。

### Phase 5：PDF AI 导入

- 文件上传；
- PyMuPDF；
- OCRmyPDF；
- PaddleOCR；
- AI 抽取；
- JSON Schema；
- 合法性验证；
- 三栏审核页；
- 多来源合并。

### Phase 6：视频导入

- FFmpeg；
- 音频转录；
- 视频时间轴；
- 关键帧；
- 棋盘变化；
- 转录对齐；
- 审核。

### Phase 7：部署

- MySQL；
- Docker Compose；
- Nginx；
- migration；
- 数据备份；
- Playwright；
- GitHub Actions。

### Phase 8：实时协作

- Yjs；
- pycrdt；
- LMDB；
- awareness；
- 协作研讨室；
- 草稿发布到正式 SQL。

---

## 16. MVP 验收标准

第一版 MVP 不包含 AI、Lichess 或多人协作，但必须完成：

1. 可以新建课程和模块；
2. 可以从起始局面或 FEN 开始；
3. 可以在棋盘上走合法棋；
4. 可以增加多个分支；
5. 可以回到父节点和切换分支；
6. 转置局面可以识别或建立引用；
7. 可以给局面和着法添加 Markdown 说明；
8. 可以关联手工资料来源；
9. 可以导入含分支的 PGN；
10. 可以导出 PGN；
11. 导入再导出不能丢失核心变化；
12. 后端拒绝非法棋步；
13. 前端使用 SWR 读取正式数据；
14. 数据库 migration 可从空库执行；
15. 自动测试覆盖 PGN round-trip 和 position key。

---

## 17. 第一批 Codex 任务

### 任务 1：初始化仓库

建立：

- `frontend/`
- `backend/`
- `docs/`
- `data/`
- pnpm
- uv
- React 18
- Vite 7
- React Router 7
- SWR
- Ant Design
- Tailwind
- Sanic
- sanic-ext
- SQLAlchemy
- Alembic
- SQLite
- pytest
- Vitest

要求：

- 前端和后端可独立启动；
- Vite proxy 指向 Sanic；
- `/api/health` 返回健康状态；
- CI 执行类型检查、lint 和测试。

### 任务 2：实现最小领域模型

实现：

- Position
- MoveEdge
- Source
- Course
- CourseModule
- KnowledgeNote

要求：

- Alembic migration；
- Pydantic Schema；
- Sanic API；
- OpenAPI；
- 生成 TypeScript 类型。

### 任务 3：实现 PGN round-trip

- 上传或粘贴 PGN；
- 使用 python-chess 解析主线和分支；
- 将局面写入图；
- 使用 position key 合并相同局面；
- 重新导出 PGN；
- 测试注释、分支、NAG 和起始 FEN。

### 任务 4：实现课程编辑页面

- 课程列表；
- 课程页面三栏布局；
- react-chessboard；
- chess.js；
- 当前节点直接候选着；
- 章节导航；
- 说明编辑；
- 保存到后端。

---

## 18. 开发约束

1. 不擅自引入未批准的大型框架；
2. 不为了未来扩展提前加入分布式架构；
3. 正式数据只通过后端写入数据库；
4. 前端 chess.js 不是最终权威；
5. 所有持久化棋步必须由 python-chess 验证；
6. PGN 不是唯一内部模型；
7. AI 输出不能绕过审核直接进入正式知识库；
8. WebSocket 只用于通知和协作，不替代正式 HTTP API；
9. 关键领域行为必须有测试；
10. 新的架构决定写入 `docs/adr/`；
11. 不复制合作项目中的 reducer、ZeroMQ、完整镜像和 Remote ESM；
12. 代码优先清晰、可读和可调试，而非过度抽象。

---

## 19. 项目成功标准

项目成功不等于“导入了最多资料”，而是形成持续学习闭环：

```text
棋书 / 视频 / 实战
        ↓
结构化局面与解释
        ↓
个人开局库和课程
        ↓
交互练习与指定局面对弈
        ↓
Lichess 实战
        ↓
错误匹配与新练习
        ↓
更新个人知识体系
```

最终系统应帮助用户回答：

- 这个局面我学过什么？
- 不同作者如何看待它？
- 我准备在实战中走什么？
- 我最近是否在这里犯过错误？
- 这个错误是否重复出现？
- 我应该复习哪一个课程或残局定式？
- 哪些内容仍未审核？
- 我的选择是否客观可行？
- 我是否真正掌握了这类局面？
