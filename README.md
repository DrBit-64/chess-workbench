# ChessWorkbench

ChessWorkbench 是一个单用户、本地优先的国际象棋知识整理、交互训练、实战复盘与 AI 辅助导入平台。当前仓库已完成第一阶段工程底座；领域功能会按照[开发计划](docs/development-plan.md)逐步实现。

## 已完成的工程底座

- React 18 + TypeScript 5.9 + Vite 7 前端，使用 React Router、SWR、Ant Design 6 和 Tailwind CSS 4；
- Python 3.13 + Sanic + Pydantic 2 + SQLAlchemy 2 后端；
- `/api/health` 会实际执行 SQLite `SELECT 1`，不是静态假健康；
- Sanic OpenAPI → `openapi-typescript` → 前端类型，并检查生成物漂移；
- Ruff、mypy、pytest、ESLint、TypeScript、Vitest、生产构建和 smoke test；
- GitHub Actions 与本地使用相同的验收入口。

## 环境要求

- Node.js 22
- pnpm 10
- Python 3.13
- uv
- Make

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

`make acceptance` 会先用锁文件安装依赖，再执行所有静态检查、类型检查、单元/集成测试、API 契约漂移检查和前端生产构建，最后自动启动前后端，同时验证 API 直连和 Vite 代理链路并清理进程；它可直接用于 clean checkout，不需要人工打开浏览器判断成功。

修改后端 API Schema 后，执行：

```bash
make contracts
```

生成并提交 `backend/openapi.json` 和 `frontend/src/types/api.generated.ts`。CI 会拒绝不同步的生成物。

## 项目文档

- [项目说明](docs/chess-workbench-project-description.md)
- [开发计划与验收矩阵](docs/development-plan.md)
- [架构概览](docs/architecture.md)
- [架构决策记录](docs/adr/README.md)
