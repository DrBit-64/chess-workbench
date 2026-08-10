# DS-GATE-01：固定 MySQL 镜像并建立累计 Stage 3/CI 门禁

## 任务类型与目标

这是一个给 DeepSeek/Deep Code 的有界配置、测试与门禁接线任务。DS-MYSQL-01 已证明真实
MySQL Alembic 往返与基础 CRUD 正确；本任务负责让本地和 CI 的正式入口可靠执行该检查，并
让 Stage 3 的依赖链真正累计。

完成后的执行关系必须是：

```text
2D → 3A → 3B → 3C → 3D → verify → smoke
                              ↑
               real MySQL, never silent skip
```

CI 继续只调用稳定入口 `make acceptance`；该入口必须指向累计的 `acceptance-stage-3`。

本任务不修复 PGN、Source API、Course.mode 业务不变量或覆盖率缺口，也不修改任何业务代码。

## 冻结输入

Codex 于 2026-08-09 使用 `docker buildx imagetools inspect mysql:8.4` 核验了 Docker Official
Image 的多架构 OCI index。两个使用位置必须固定为完全相同的镜像引用：

```text
mysql:8.4@sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb
```

该 index 对应 MySQL 8.4.11，并包含 CI 所需的 `linux/amd64` manifest。不得在本任务中改回
mutable tag、改用平台专属 digest，或自行升级到另一个 digest。

## 开始前

1. 按 `project-handoff` skill 读取 `AGENTS.md`、`PLANS.md`、
   `docs/agent/HANDOFF.md` 和本任务全文。
2. 运行 `git status --short`、`git log --oneline -5`、
   `git show --stat --oneline HEAD`。
3. 父实现基线应为 `0705701 feat(codex): pass DS-MYSQL-01`；HEAD 可以再包含一个仅提交本
   任务包、PLANS 与 HANDOFF 的 Codex 文档 commit。除此之外不应有未提交修改；若存在其他
   代码修改，停止并交回用户处理。
4. 不提交、不 rebase、不 reset、不安装依赖；需要这些操作时先询问用户。

## 允许修改的文件

- `Makefile`
- `.github/workflows/ci.yml`
- `scripts/check_mysql.py`
- `backend/tests/test_check_mysql_script.py`
- 可新增 `backend/tests/test_acceptance_wiring.py`
- `docs/agent/HANDOFF.md`

除非停止并交回 Codex 重新划分任务，不得修改业务代码、migration、其他测试、覆盖率阈值、
lockfile、依赖、ADR、PGN fixture 或生成契约。

## 必须实现的行为

### 1. 固定并统一 MySQL 镜像

- `scripts/check_mysql.py --container` 必须使用上面的完整 tag+digest 引用。
- GitHub Actions 的 MySQL service 必须使用同一个完整引用并保留 healthcheck。
- 镜像引用应在脚本中使用有语义的常量，不能把长 digest 埋在 Docker argv 中。
- 增加自动断言，证明脚本和 CI 使用完全相同的完整引用，并证明引用包含
  `mysql:8.4@sha256:` 加 64 位十六进制 digest。把任一位置恢复为 `mysql:8.4` 时测试必须失败。

### 2. 让 Stage 3 Make 目标严格累计

保持各单元现有测试命令不变，只修正依赖关系和聚合入口：

- `acceptance-stage-3a` 依赖 `acceptance-stage-2d`；
- `acceptance-stage-3b` 依赖 `acceptance-stage-3a`；
- `acceptance-stage-3c` 依赖 `acceptance-stage-3b`；
- `acceptance-stage-3d` 依赖 `acceptance-stage-3c`；
- `acceptance-stage-3` 依赖 `acceptance-stage-3d` 和前端 bootstrap，然后执行完整
  `verify` 与 `smoke`；
- 稳定 CI 入口 `acceptance` 依赖 `acceptance-stage-3`，不再停留在 Stage 2。

增加确定性的配置契约测试，逐条断言上述依赖，避免仅凭人工阅读 Makefile 验收。删除任一
依赖或把 `acceptance` 改回 Stage 2 时，测试必须失败。

### 3. Stage 3D 不得静默跳过，并复用安全脚本

- 定义仅供门禁使用、不会影响普通应用测试的 Make 变量，例如
  `MYSQL_ACCEPTANCE_URL ?= $(CHESS_WORKBENCH_MYSQL_URL)`；不要 export 它。
- 若 `MYSQL_ACCEPTANCE_URL` 非空，`acceptance-stage-3d` 必须把它作为
  `CHESS_WORKBENCH_MYSQL_URL` 只传给 `scripts/check_mysql.py` 的外部 URL 模式。
- 若该变量为空，本地门禁必须运行 `scripts/check_mysql.py --container`，而不是成功跳过。
- 两条路径都必须复用脚本已有的空 schema 防护、双 URL 传递、pytest 参数、timeout 与清理
  行为；不要在 Makefile 或 CI 再复制一套 pytest 命令。
- 配置契约测试必须证明 3D 目标没有 silent-skip 文案/分支，并同时存在外部 URL 路径和
  `--container` fallback。

### 4. CI 只调用同一个累计入口

- 保留单个 MySQL service、healthcheck、Node/pnpm/uv frozen 安装流程。
- CI 的正式验收步骤只运行 `make acceptance`，并通过 `MYSQL_ACCEPTANCE_URL` 把 service URL
  提供给 Stage 3D。
- 删除当前重复的“Run MySQL compatibility tests” pytest 步骤；MySQL 只能由累计 Make 链执行
  一次。
- 不要把 `CHESS_WORKBENCH_DATABASE_URL` 或 `CHESS_WORKBENCH_MYSQL_URL` 设置为整个 job 的环境
  变量，否则后续 `verify` 的普通测试可能意外改用 MySQL。脚本会在自己的 pytest 子进程中
  设置所需的两个 URL。
- 自动断言 CI 包含唯一的 `make acceptance` 调用、提供 `MYSQL_ACCEPTANCE_URL`，且不直接调用
  `test_mysql_compat.py`。

## 必须新增或保留的自动断言

1. 脚本与 CI 使用同一个固定 tag+digest；mutable tag 的反例会失败。
2. Make 的 3A/3B/3C/3D/aggregate/acceptance 六段依赖关系逐条正确。
3. 3D 无 URL 时走一次性容器，有 URL 时走脚本的安全外部模式，任何路径都不会成功 skip。
4. CI 只通过 `make acceptance` 执行 MySQL，且没有第二套直接 pytest 命令。
5. DS-MYSQL-01 的六个脚本控制流测试继续通过。

配置测试可以读取仓库文件，但必须按 `Path(__file__)` 推导仓库根目录，不能依赖 pytest 的
当前工作目录或测试执行顺序。断言应针对语义所需的目标、变量和命令，避免快照整个文件。

## 明确不在本任务处理的事项

- 不把全局 branch floor 从当前值提升到 75%，也不调整 85%/89% focused floor；这些缺口要靠
  后续业务与反例测试补齐，不能在纯门禁任务中制造一个必然失败的基线。
- 不修复 Stage 2C 内容 API、Stage 2D 业务不变量或 PGN 语义。
- 不修改 Actions 自身的版本引用、生产 Compose 或 Stage 10 部署配置。
- 不以 `continue-on-error`、`|| true`、条件跳过或取消 healthcheck 让 CI 变绿。

## 验收命令

先运行聚焦验证：

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_check_mysql_script.py backend/tests/test_acceptance_wiring.py --no-cov
make backend-static
git diff --check
```

唯一聚合验收命令：

```bash
make acceptance
```

本地未提供 `MYSQL_ACCEPTANCE_URL` 时，该命令必须自行启动固定 digest 的一次性 MySQL，实际
执行 3 个 MySQL 测试且无 skip/xfail，随后停止容器；还必须从日志证明 3A、3B、3C、3D、
`verify` 和 `smoke` 均执行并最终退出 0。若本机 Docker、Node/pnpm 或其他必要工具不可用，
必须如实记录未验收，不能以 `make -n` 或单元测试代替聚合验收。

## 交付记录

完成后只更新 `docs/agent/HANDOFF.md` 中与 DS-GATE-01 有关的当前状态，记录：

- 精确修改文件；
- 最终 Make 依赖链；
- 固定镜像引用；
- 聚焦命令和唯一聚合命令的退出码、测试数、skip/xfail；
- MySQL 使用外部 service 还是一次性容器，以及容器清理结果；
- CI 中删除的重复路径；
- 未解决问题与下一步建议。

不要自行提交；把完整 diff 留给 Codex 做最终审查。
