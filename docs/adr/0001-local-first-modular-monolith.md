# ADR 0001：从本地优先模块化单体开始

- 状态：Accepted
- 日期：2026-08-05

## 背景

项目首先服务单个用户，但长期可能增加后台计算、MySQL 部署和实时协作。过早引入分布式队列、缓存和协作数据层会显著增加一致性与调试成本。

## 决定

第一阶段采用 React SPA + Sanic API + SQLAlchemy + SQLite 的模块化单体。正式数据只通过 API 写入 SQL。未来的 worker 通过 SQL 任务表协调；WebSocket 只通知客户端重新取数；协作草稿即使使用 Yjs/LMDB，也必须显式发布后才能进入正式 SQL。

## 后果

- 本地启动和备份简单，核心测试无需外部服务；
- 领域模块必须与 Sanic 传输层解耦，避免模块化单体退化为路由脚本集合；
- SQLite 之后必须用 MySQL 集成测试约束可移植性；
- Redis、Celery、ZeroMQ、GraphQL 和独立图数据库不进入当前范围。
