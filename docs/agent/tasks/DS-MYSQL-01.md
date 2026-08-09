# DS-MYSQL-01：真实 MySQL Alembic 往返门禁

## 任务类型与目标

这是一个给 DeepSeek/Deep Code 的有界 bug-fix + 测试任务。修复 migration 0002 在真实 MySQL
上的 downgrade，并让现有 Stage 3D 测试真正执行 Alembic，而不是用
`Base.metadata.create_all/drop_all` 冒充 migration 验证。

本任务只证明当前 schema 可以在一次性 MySQL 8.4 数据库中完成：

```text
empty schema → upgrade head → alembic check → downgrade base → upgrade head → CRUD checks
```

它不负责 PGN、API、Course.mode 业务不变量、Make/CI 累积接线或镜像 digest。

## 开始前

1. 按 `project-handoff` skill 读取 `AGENTS.md`、`PLANS.md`、
   `docs/agent/HANDOFF.md`，并执行 `git status --short`、`git log --oneline -5`、
   `git show --stat --oneline HEAD`。
2. 若当前 working tree 含不属于本任务的未提交修改，停止并让用户先提交 Codex 文档，或在
   独立 Git worktree/branch 中执行。不要让两个 agent 编辑同一个 dirty working tree。
3. 不提交、不 rebase、不 reset、不安装依赖；需要这些操作时先询问用户。

## 允许修改的文件

- `backend/migrations/versions/20260806_0002_content_context.py`
- `backend/migrations/versions/20260806_0001_position_graph.py`，仅当完整 downgrade 暴露同类问题
- `backend/tests/test_mysql_compat.py`
- `scripts/check_mysql.py`
- `docs/agent/HANDOFF.md`

除非先停止并交回 Codex 重新划分任务，不得修改模型、Schema、service、API、PGN 模块、
Makefile、CI、lockfile、依赖或 ADR。

## 必须实现的行为

### 1. 修复真实 downgrade

- 保持 upgrade 后的表、列、约束和索引语义不变。
- 修复 MySQL 8.4 在 migration 0002 downgrade 时抛出的错误 1553：当前代码在删除
  `source_spans` 表之前显式删除一个仍被外键需要的索引。
- 检查该 migration 中所有“紧接着 drop_table 的显式 drop_index”；若完整往返证明它们同样
  冗余，就让 `drop_table` 负责删除本表索引，避免只修第一个报错。
- 不得通过关闭外键检查、捕获并忽略 SQL 错误、只在 SQLite 分支执行，或改用 metadata
  create/drop 绕过 Alembic。

### 2. 用 Alembic API 取代伪 migration 测试

- `test_mysql_compat.py` 必须实际调用 `alembic.command.upgrade(config, "head")`、
  `alembic.command.check(config)`、`alembic.command.downgrade(config, "base")`。
- Alembic env 会从 Settings 覆盖 ini URL，因此测试进程必须同时设置
  `CHESS_WORKBENCH_DATABASE_URL` 为测试 MySQL URL；只设置
  `CHESS_WORKBENCH_MYSQL_URL` 不够。
- Alembic 同步命令必须在没有运行 asyncio event loop 的同步上下文执行。
- head 后断言当前 revision 精确为 `20260806_0003`，并断言代表三次 migration 的关键表存在，
  至少包括 `positions`、`courses`、`source_spans`、`knowledge_notes`。
- `alembic check` 必须在真实 MySQL head schema 上执行并通过。
- base 后断言 current revision 为 `None`，且除 Alembic 自身表外没有本项目业务表。
- 往返测试结束前再次 upgrade head；后续 CRUD 与 position 唯一性测试必须使用 migration 创建的
  schema，不得调用 `Base.metadata.create_all/drop_all`。
- 测试不得依赖偶然的 pytest 函数顺序；用明确 fixture 或等价机制保证 schema 前置状态。

### 3. 让本地脚本给出可信结果

- `scripts/check_mysql.py --container` 启动一次性 MySQL 后，为 pytest 同时传入上述两个 URL
  环境变量。
- pytest 子进程显式使用 `-o addopts='' --no-cov`，避免项目默认覆盖率参数把本专用集成门禁
  混成不相关的全仓覆盖率检查。
- 给 pytest 子进程设置有限 timeout；无论启动、等待、migration 或测试在哪一步失败，都在
  `finally` 中停止本次脚本创建的容器。
- 外部 URL 模式只能对空 schema 运行；发现已有 Alembic revision 或项目业务表时必须拒绝，
  不能清空用户数据库。
- 本任务不改变 `mysql:8.4` tag；镜像 digest 在后续独立任务处理。

## 必须新增/保留的自动断言

1. 真实 MySQL 的 `upgrade head → check → downgrade base → upgrade head` 完成。
2. head revision、关键表集合、base revision 和 base 业务表集合均有显式断言。
3. 课程 CRUD 与 position key 唯一性在 Alembic 创建的 head schema 上继续通过。
4. 运行本任务入口时 MySQL 测试全部执行，不能 skip/xfail。
5. 恢复旧的 `drop_index("ix_source_spans_source_version_id", ...)` 应重新触发真实失败；把 Alembic
   往返替换为 metadata create/drop 也必须因 revision/schema 断言而失败。

不得降低覆盖率阈值、删除断言、增加宽泛异常吞噬或以 mock 数据库代替真实 MySQL。

## 唯一验收命令

从仓库根目录运行：

```bash
uv run --project backend --locked python scripts/check_mysql.py --container
```

完成标准：命令退出 0；输出显示所有 MySQL 测试实际执行且无 skipped/xfail；容器在成功和失败
路径都会停止。若本机 Docker 不可用，必须如实记录“未验收”，不能以 SQLite 结果代替。

## 交付记录

完成后只更新 `docs/agent/HANDOFF.md` 中与本任务有关的段落，记录：

- 精确修改文件；
- migration bug 的根因和修复；
- 唯一验收命令、退出码、pass/skip 数；
- 是否使用一次性容器；
- 未解决问题与下一步建议。

不要自行提交；把 diff 留给 Codex 做最终审查。
