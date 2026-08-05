# 架构概览

## 当前决策

ChessWorkbench 从一个本地优先的模块化单体开始：React SPA 通过 HTTP 读取和写入 Sanic API，正式数据只保存在 SQL 数据库中。第一阶段使用 SQLite；领域稳定后增加 MySQL/MariaDB 兼容测试。

```text
React SPA
  └─ SWR /api/*
       └─ Sanic application services
            └─ SQLAlchemy → SQLite（后续 MySQL）
```

后台任务、Stockfish、OCR、AI 和 WebSocket 会在对应阶段进入系统，但不会改变以下边界：

1. 后端 SQL 数据是正式事实源；
2. 前端 `chess.js` 只能做交互预检，持久化棋步由 `python-chess` 验证；
3. PGN 是导入导出格式，Position/MoveEdge 局面图才是内部模型；
4. Source、Knowledge、Repertoire、Exercise 是不同领域概念；
5. WebSocket 只发轻量失效通知，客户端收到后由 SWR 重新取数；
6. AI 结果先进入候选和审核流程，不能直接写入正式知识。

## 代码边界

- `frontend/src/app`：路由和应用外壳；
- `frontend/src/components`：跨功能展示组件；
- `frontend/src/logic/api`：HTTP 客户端与从生成契约派生的类型；
- `backend/src/chess_workbench/api`：传输层与应用组装；
- `backend/src/chess_workbench/schemas`：Pydantic API 契约；
- `backend/src/chess_workbench/store`：数据库基础设施；
- 后续领域模块会放入 `backend/src/chess_workbench/domain`，不依赖 Sanic 请求对象。

## 契约链路

Pydantic Schema 通过 Sanic Extensions 形成 OpenAPI。`scripts/contracts.py` 从真实 `/docs/openapi.json` 导出确定性文件，再由 `openapi-typescript` 生成前端类型。前端不得另写一份相同 DTO；`make check-contracts` 会比较重新生成结果并在漂移时失败。

## 运行时数据

默认 SQLite URL 指向 `data/database/chess-workbench.db`。目录由数据库适配层按需创建，clean checkout 不依赖被忽略的数据文件。测试注入临时 SQLite URL，避免污染个人数据。

## 尚未作出的决定

Position identity、课程上下文如何引用全局图、PGN occurrence 模型、版本审计、任务租约与重试等会在进入相应阶段前单独写 ADR，避免在脚手架阶段凭空固化。
