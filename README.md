# ChessWorkbench

ChessWorkbench 是一个单用户、本地优先的国际象棋知识整理、交互训练、实战复盘与 AI 辅助导入平台。当前仓库已完成 Stage 4 编辑器 MVP，并实现 Stage 6A–6D 本地引擎工作台；范围、状态和机器验收标准以[开发计划](docs/development-plan.md)为准。

## 已完成的工程底座

- React 18 + TypeScript 5.9 + Vite 7 前端，使用 React Router、SWR、Ant Design 6 和 Tailwind CSS 4；
- Python 3.13 + Sanic + Pydantic 2 + SQLAlchemy 2 后端；
- `/api/health` 会实际执行 SQLite `SELECT 1`，不是静态假健康；
- Sanic OpenAPI → `openapi-typescript` → 前端类型，并检查生成物漂移；
- Ruff、mypy、pytest、ESLint、TypeScript、Vitest、生产构建和 smoke test；
- GitHub Actions 与本地使用相同的验收入口。

## 环境要求

- Node.js 22
- pnpm 10.14.0（由仓库的 `packageManager` 字段锁定；也可只提供 Corepack）
- Python 3.13
- uv
- Make

Make 会优先使用全局 `pnpm`，找不到时自动回退到 `corepack pnpm`。如两者都不可用，先执行：

```bash
corepack enable
corepack prepare pnpm@10.14.0 --activate
```

因此不再要求为了运行 `make acceptance` 单独安装全局 pnpm。

## 启动

```bash
cp .env.example .env
make bootstrap
make install-stockfish
make install-chess-diagram-model
```

分别在两个终端启动 API 和前端：

```bash
make dev-api
make dev-web
```

`make dev-api` 会先把本地数据库升级到最新版本，再启动服务。访问 `http://127.0.0.1:5173`；
Dashboard、Learn、Sources、三栏课程编辑器与“引擎”工作台均可直接操作。引擎页默认显示
四条 Stockfish 主变，包含白方视角评分、WDL、深度/节点，并可从任意 FEN 对弈和保存复盘
课程草稿。Syzygy 表可选放入 `data/tablebases/syzygy/`。API 文档的机器可读契约位于
`http://127.0.0.1:8000/docs/openapi.json`。

要运行 Stage 8C PDF AI 候选提取，把密钥保存到仓库外的普通 UTF-8 文件（建议
`~/.config/chess-workbench/deepseek-api-key`），将文件权限设为 `600`，然后只在本地 `.env`
中设置 `CHESS_WORKBENCH_DEEPSEEK_API_KEY_FILE` 为它的绝对路径。程序拒绝从 `.env` 直接读取
`CHESS_WORKBENCH_DEEPSEEK_API_KEY`，也会拒绝组或其他用户可读的密钥文件。未配置密钥文件时
其他功能仍可用，但新的 v2 提取任务会以 `provider_unconfigured` 明确失败。
扫描棋书中的起始局面图由本地、可替换的 ONNX 识别器处理；模型通过上述安装命令放入
`data/models/chess-diagram/`，识别证据随后仍进入与普通 PDF 正文完全相同的提取请求。

## 自动验收

```bash
make acceptance
```

`make acceptance` 会先用锁文件安装依赖和校验 Stockfish 18，再累计执行 Stage 2–6 门禁、真实 MySQL 8.4
兼容性检查、所有静态检查、类型检查、单元/集成测试、API 契约漂移检查、前端生产构建、
双服务 smoke 和 Chromium 编辑器关键路径；测试数据库与进程会自动创建和清理。当前它是
`make acceptance-stage-6` 的稳定别名。

各阶段可按依赖关系逐层验收：

```bash
make acceptance-stage-2a  # 局面身份、棋规向量和异步数据库配置
make acceptance-stage-2b  # 另含模型、仓储、约束和 migration 往返
make acceptance-stage-2c  # 另含课程语境 Schema、CRUD API 和错误事务
make acceptance-stage-2d  # 双模课程与来源笔记约束
make acceptance-stage-3   # PGN 语义导入/导出与 MySQL
make acceptance-stage-4a  # Dashboard、Learn、Sources
make acceptance-stage-4b  # 棋盘、当前路径、分支与转置
make acceptance-stage-4c  # Markdown、来源、历史、恢复与发布
make acceptance-stage-4   # 全仓检查、smoke 与 Chromium 编辑器 E2E
make acceptance-stage-6a  # SQL job 状态机、租约、重试和取消
make acceptance-stage-6b  # fake/真实 Stockfish、MultiPV 与缓存
make acceptance-stage-6c  # Syzygy、纯判定与失效通知
make acceptance-stage-6   # 对弈、复盘、课程草稿与全仓累计门禁
```

这些目标是累积的：后一个目标会先运行它所依赖的前置门禁。

修改后端 API Schema 后，执行：

```bash
make contracts
```

生成并提交 `backend/openapi.json` 和 `frontend/src/types/api.generated.ts`。CI 会拒绝不同步的生成物。

## 项目文档

- [AGENTS.md](AGENTS.md) — long-term rules for coding agents
- [PLANS.md](PLANS.md) — current task plan
- [项目说明](docs/chess-workbench-project-description.md)
- [开发计划与验收矩阵](docs/development-plan.md)
- [架构概览](docs/architecture/overview.md)
- [架构决策记录](docs/decisions/README.md)
