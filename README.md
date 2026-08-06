# ChessWorkbench

ChessWorkbench 是一个单用户、本地优先的国际象棋知识整理、交互训练、实战复盘与 AI 辅助导入平台。当前仓库已完成第一阶段工程底座，Stage 2 领域内核正在实施；范围、状态和机器验收标准以[开发计划](docs/development-plan.md)为准。

## 已完成的工程底座

- React 18 + TypeScript 5.9 + Vite 7 前端，使用 React Router、SWR、Ant Design 6 和 Tailwind CSS 4；
- Python 3.13 + Sanic + Pydantic 2 + SQLAlchemy 2 后端；
- `/api/health` 会实际执行 SQLite `SELECT 1`，不是静态假健康；
- Sanic OpenAPI → `openapi-typescript` → 前端类型，并检查生成物漂移；
- Ruff、mypy、pytest、ESLint、TypeScript、Vitest、生产构建和 smoke test；
- GitHub Actions 与本地使用相同的验收入口。

## 环境要求

- Node.js 22
- pnpm 10.14.0（由仓库的 `packageManager` 字段锁定）
- Python 3.13
- uv
- Make

推荐通过 Node.js 自带的 Corepack 启用 pnpm：

```bash
corepack enable
corepack prepare pnpm@10.14.0 --activate
```

依赖前端或契约工具的 Make 目标会先检查 pnpm；缺失时会直接给出上述修复方式，而不是留下难以定位的子进程错误。

## 启动

```bash
cp .env.example .env
make bootstrap
```

分别在两个终端启动 API 和前端：

```bash
make dev-api
make dev-web
```

访问 `http://127.0.0.1:5173`。API 文档的机器可读契约位于 `http://127.0.0.1:8000/docs/openapi.json`。

## 自动验收

```bash
make acceptance
```

`make acceptance` 会先用锁文件安装依赖，再执行当前阶段门禁、所有静态检查、类型检查、单元/集成测试、API 契约漂移检查和前端生产构建，最后自动启动前后端，同时验证 API 直连和 Vite 代理链路并清理进程；它可直接用于 clean checkout，不需要人工打开浏览器判断成功。当前它是 `make acceptance-stage-2` 的薄别名，因此 GitHub Actions 的稳定入口也会运行 Stage 2 分层门禁。

Stage 2 可以按依赖关系逐层验收：

```bash
make acceptance-stage-2a  # 局面身份、棋规向量和异步数据库配置
make acceptance-stage-2b  # 另含模型、仓储、约束和 migration 往返
make acceptance-stage-2c  # 另含课程语境 Schema、CRUD API 和错误事务
make acceptance-stage-2   # 另含全仓检查、契约漂移、前端构建和 smoke
```

这些目标是累积的：后一个目标会先运行前面的目标。Stage 2 仍处于实施中；只有 `make acceptance-stage-2` 在 clean checkout 退出码为 0，才表示该阶段满足计划中的自动验收门槛。

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
