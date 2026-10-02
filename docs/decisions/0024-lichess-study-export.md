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
2. 大章节自身的棋谱先导出，再按小节顺序导出后代。使用 `大章节 / 小节` 作为 `ChapterName`，保留原 PGN 的对局标签。纯目录／无棋谱条目不创建空棋谱，并在预览列出。每个活动小节本来就只有一个根，不引入新棋谱模型。
3. 复用现有 occurrence PGN exporter，给本次导出额外提供已批准局部说明与章节正文。PGN 不承载 PDF 文件、图片、原书定位链接、Markdown 版式或完整课程层级；界面说明此边界。
4. 服务端从仓库外的 `CHESS_WORKBENCH_LICHESS_API_TOKEN_FILE` 读取令牌，仅需 `study:write`。令牌不存前端、URL、课程数据库或 Git。复用已有秘密文件加载规则。
5. 固定向官方 `https://lichess.org` 创建新研讨，默认 `unlisted`（持链接可看），界面明确告知。调查的 `StudyMaker.apply(FormData)` 没有把表单 visibility 传入 `Study.make`，而后者默认 unlisted，因此本版不提供未经证实的 private 选项，也不承诺私有；用户可在 Lichess 修改可见性。
6. 一次点击顺序执行创建、批量导入两个请求；不自动重试写请求，不更新／删除用户既有研讨，不做双向同步。预先检查服务端的真实容量限制，不静默截断。
7. 已取得研讨 ID 后，即便导入失败或不完整也返回链接和准确状态；网络错误标明远端结果可能不确定。前端保留结果，防止把部分成功当成全成功，避免自动重发。首版不新增数据库表或通用外部任务框架。

## 验证

用本地课程夹具验证层级顺序、分支、FEN、NAG、注释和范围；用 `httpx.MockTransport` 核对真实接口表单、鉴权及部分成功／限流行为；用前端定向测试验证预览、范围选择、点击发布、错误和结果链接。不在自动测试中创建真实 Lichess 研讨。
