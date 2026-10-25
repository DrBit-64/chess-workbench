# ADR 0024：从课程单向创建 Lichess 研讨

- 状态：Accepted
- 日期：2026-10-02

## 背景与调查

操作者要求在课程页把一个小节或整个大章节发到 Lichess，并接受两级标题展平。
已核对官方 API 定义和 lila 源码：

- [创建研讨](https://github.com/lichess-org/api/blob/master/doc/specs/tags/studies/api-study.yaml)：`POST /api/study`，表单编码，`study:write` 权限，会先创建一个空章节。
- [导入 PGN](https://github.com/lichess-org/api/blob/master/doc/specs/tags/studies/api-study-studyId-import-pgn.yaml)：`POST /api/study/{id}/import-pgn` 支持多局 PGN，单研讨最多 64 章。
- [StudyForm](https://github.com/lichess-org/lila/blob/master/modules/study/src/main/StudyForm.scala) 与 [StudyApi](https://github.com/lichess-org/lila/blob/master/modules/study/src/main/StudyApi.scala)：`initial=true` 会用第一个导入章节替换初始空章；响应可同时包含已创建章节与 `error`，HTTP 200 不等于全部成功。
- [StudyPgnImport](https://github.com/lichess-org/lila/blob/master/modules/study/src/main/StudyPgnImport.scala) 与 [Chapter](https://github.com/lichess-org/lila/blob/master/modules/study/src/main/Chapter.scala)：保留分支、FEN、注释与 NAG；`ChapterName` tag 优先作为标题；每章 PGN 最多 100,000 字符、3,000 棋步节点，章节标题会截到 80 字符。
- [认证说明](https://github.com/lichess-org/api/blob/master/doc/specs/lichess-api.yaml)：个人令牌足够用于这个单用户站点，无需注册 OAuth 应用。

## 决定

1. 在课程页为当前小节或整个父章节提供「发送到 Lichess」。后端预览生成待发送的有序章节清单，点击创建后发送已保存的课程内容；不修改本地知识和棋谱。
2. 2026-10-03 调整标题映射：选择大章节时，先导出同名目录章，再按小节顺序导出后代；每章的 `ChapterName` 都只用对应模块原名，不再拼接 `大章节 / 小节`。无棋谱的目录或小节以零棋步 PGN 章节保留标题，其正文可放在起始局面注释中。若大章节本身已有棋谱，该首章保留自己的棋谱，避免丢失内容。至少有一个有棋步章节才允许创建研讨。此映射只影响 Lichess 导出，不改变课程层级或原 PGN 对局标签。
3. 复用现有 occurrence PGN exporter，给本次导出额外提供已批准局部说明与章节正文。PGN 不承载 PDF 文件、图片、原书定位链接、Markdown 版式或完整课程层级；界面说明此边界。
4. 服务端从仓库外的 `CHESS_WORKBENCH_LICHESS_API_TOKEN_FILE` 读取令牌，仅需 `study:write`。令牌不存前端、URL、课程数据库或 Git。复用已有秘密文件加载规则。
5. 固定向官方 `https://lichess.org` 创建新研讨，默认 `unlisted`（持链接可看），界面明确告知。调查的 `StudyMaker.apply(FormData)` 没有把表单 visibility 传入 `Study.make`，而后者默认 unlisted，因此本版不提供未经证实的 private 选项，也不承诺私有；用户可在 Lichess 修改可见性。
6. 一次点击顺序执行创建、批量导入两个请求；不自动重试写请求，不更新／删除用户既有研讨，不做双向同步。预先检查服务端的真实容量限制，不静默截断。
7. 已取得研讨 ID 后，即便导入失败或不完整也返回链接和准确状态；网络错误标明远端结果可能不确定。前端保留结果，防止把部分成功当成全成功，避免自动重发。首版不新增数据库表或通用外部任务框架。

## 2026-10-03 课程级范围扩展

操作者进一步明确，需要将**整门课程**作为一个 Lichess 研讨发送。课程标题成为研讨名称；按课程目录顺序依次导出所有活动的一级章节及其二级小节。一级章节保留原名，若无棋谱则为零棋步目录章；二级小节也保留原名。API 中省略 `module_id` 表示整门课程，传入 `module_id` 仍按原规则导出单个章节或小节。课程设置菜单（与重命名、删除课程同处）提供专门入口，并在远端写入前显示完整章节清单和 64 章容量检查。Lichess 上仍是一层有序章节列表，目录章只是视觉分组，不建立远端父子关系。

## 2026-10-07 多选发送范围

发送窗口改为多选，可选择多个一级章节（自动包含全部二级小节），也可单独选择小节。课程设置入口默认全选一级章节；当前章节入口默认选择当前章节或小节，均允许调整。提供“全选一级章节”和“清空选择”。清空时不请求整门课程预览，也不能发布。

预览 GET 使用重复的 `module_ids` 查询参数，创建 POST 使用 `module_ids` 数组。保留已在使用的 `module_id` 单选调用和省略范围表示整门课程的调用；两种显式范围不得同时提供，显式数组不得为空。预览和发布共用同一个范围解析与 PGN 编译入口，按课程目录顺序展开、合并重叠选择，不按点击顺序导出，也不重复发送已被父章节覆盖的小节。多个章节的默认研讨名称采用课程标题；单个章节或小节沿用已有默认名称，用户修改后的名称在调整范围时保留。

继续使用整门课程的标题映射：一级章节作为目录章（已有棋谱时保留），二级小节随后排列，各自使用原名。容量检查按实际展开后去重的研讨章节总数计算，超过现有上限时要求缩小选择；不静默截断、不拆成多个研讨、不引入新数据库或后台任务。

## 验证

用本地课程夹具验证层级顺序、分支、FEN、NAG、注释和范围；用 `httpx.MockTransport` 核对真实接口表单、鉴权及部分成功／限流行为；用前端定向测试验证预览、范围选择、点击发布、错误和结果链接。不在自动测试中创建真实 Lichess 研讨。
