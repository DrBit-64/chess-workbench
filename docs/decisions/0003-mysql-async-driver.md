# ADR 0003：异步 MySQL 驱动选择 asyncmy

- 状态：Accepted
- 日期：2026-08-06

## 背景

后端已经使用 SQLAlchemy `AsyncEngine`，SQLite 由 `aiosqlite` 驱动。项目说明最初列出
PyMySQL，但 PyMySQL 是同步 DBAPI，不能作为 SQLAlchemy 异步引擎的 MySQL 驱动。为了在
Stage 3D 建立 SQLite/MySQL 双库阻塞测试，必须先锁定异步方言和连接 URL。

## 决定

- MySQL/MariaDB 的 SQLAlchemy 异步驱动选择 `asyncmy`；
- 连接 URL 使用 `mysql+asyncmy://user:password@host/database`；
- 首个锁定版本为 `asyncmy 0.2.11`，其 Python 3.13 wheel 进入项目锁文件；
- `aiomysql` 保留为驱动不再兼容时的回退候选，但当前不作为运行时依赖；
- 不把同步 PyMySQL 传给 `create_async_engine`，也不为 MySQL 单独建立一套同步 repository；
- Stage 2A 只通过 ADR 和配置/URL 约束锁定选择；真实 MySQL、migration 与同一领域夹具的
  双库门禁在 Stage 3D 引入。

## 理由

- `asyncmy` 提供 SQLAlchemy 支持的原生 asyncio 方言，保持当前异步 repository 边界；
- Python 3.13 有可锁定的预编译 wheel，clean checkout 不需要现场编译驱动；
- API 和未来 worker 可以复用相同 SQLAlchemy 异步会话模型；
- 驱动差异通过 Stage 3D 的真实 MySQL 集成测试暴露，而不是在业务代码中加入方言分支。

## 后果

- 本地 MVP 仍默认使用 SQLite/aiosqlite，不要求安装或运行 MySQL；
- MySQL 配置必须明确使用 `mysql+asyncmy`，错误地使用 `mysql+pymysql` 应在配置验证阶段失败；
- repository、migration 和 Schema 不得依赖 SQLite 特有的布尔、JSON、排序或唯一约束行为；
- 若未来更换驱动，必须用新 ADR 取代本决定，并让相同的双库行为夹具全部通过。
