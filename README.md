# ChessWorkbench

一个单用户、本地优先的国际象棋学习网站。你可以导入 PGN、编辑和学习课程、用 Stockfish 分析局面，也可以从 PDF 棋书中提取棋谱，经人工审核后发布到课程，并继续追加后面的页段。

课程、原始文件和提取记录默认保存在自己的电脑上。PDF AI 提取需要调用外部模型，会将选定页段及续接所需的前文信息发送给配置的供应商，并产生 API 费用；不配置模型也可以使用课程和 PGN 等功能。

个人开局库、间隔复习和 Lichess 对局导入尚未完成，见[当前开发计划](docs/development-plan.md)。

## 环境准备

下面以 **Linux / Windows WSL2** 的终端为例。Windows 用户请在 WSL2 内安装依赖和运行项目。其他系统需要自行准备兼容的依赖和 Stockfish；仓库中的引擎自动安装脚本只提供 Linux x64 二进制。

| 工具 | 版本 / 用途 |
| --- | --- |
| Git | 下载项目 |
| Node.js | **22.x**，运行前端 |
| pnpm | **10.14.0**，安装前端依赖 |
| uv | 安装 Python 环境和后端依赖 |
| Python | **3.13**，可以交给 uv 安装 |
| GNU Make、Bash | 执行仓库中的安装和启动命令 |

安装好 Node.js、uv、Git 和 Make 后，准备 Python 和 pnpm：

```bash
uv python install 3.13
npm install -g pnpm@10.14.0
```

默认使用 SQLite，**不需要另外安装数据库、Redis 或 Docker**。首次安装需要联网下载依赖；安装本地引擎和棋盘识别模型时也需要联网。

## 首次启动

### 1. 下载并安装

```bash
git clone https://github.com/DrBit-64/chess-workbench.git
cd chess-workbench
cp .env.example .env
make bootstrap
```

保留 `.env` 默认配置即可先运行网站。以下命令都在项目根目录执行。

### 2. 启动后端

在第一个终端运行：

```bash
make dev-api
```

这个命令会自动创建 / 升级数据库，再启动 API 和后台任务处理器。默认地址是 `http://127.0.0.1:8000`。

### 3. 启动前端

另开一个终端，进入同一个项目目录后运行：

```bash
make dev-web
```

浏览器打开 **http://127.0.0.1:5173**。两个终端都需要保持运行；停止时分别按 `Ctrl+C`。以后再次使用，直接运行这两个启动命令即可，不需要重新复制 `.env`。

前端会把 `/api` 请求和 WebSocket 连接转发给后端，无需单独配置跨域。

### 4. 开始使用

- **学习**：创建书籍、章节和课程内容，导入 PGN，编辑棋谱和学习已有课程。
- **资料**：上传自己的 PDF，选择物理页码范围提取，在审核页修正棋谱，再批准并发布到课程；后续可以从下一页连续追加提取。需要先完成下面的模型配置。
- **引擎**：分析局面、查看变化，或与引擎对弈。需要先安装 Stockfish。

仓库不附带棋书或个人课程，首次启动没有示例书籍。PDF 页码从文件第一页算起，可能与书上印刷的页码不同。初次提取建议选择一个完整例局；后续增量提取可以续接跨页棋局。

## 可选：启用本地引擎

Linux x64 环境执行：

```bash
make install-stockfish
```

安装后重启后端。默认安装位置是 `data/engines/stockfish-18/stockfish`。

如果已经有适合自己系统的 Stockfish，在 `.env` 中指定其可执行文件的绝对路径即可：

```dotenv
CHESS_WORKBENCH_STOCKFISH_PATH=/absolute/path/to/stockfish
```

引擎的线程数和内存上限可通过 `.env` 中的 `CHESS_WORKBENCH_ENGINE_MAX_THREADS` 和 `CHESS_WORKBENCH_ENGINE_MAX_HASH_MB` 调整。Syzygy 残局表库是可选的，默认目录为 `data/tablebases/syzygy/`。

## 可选：启用 PDF AI 提取

### 配置模型和密钥

当前代码默认使用 DeepSeek 的 `deepseek-v4-flash`。需要自行准备供应商账户和 API 额度。

先在**仓库外**创建密钥文件：

```bash
mkdir -p ~/.config/chess-workbench
touch ~/.config/chess-workbench/provider-api-key
chmod 600 ~/.config/chess-workbench/provider-api-key
```

用文本编辑器将 API 密钥写入该文件，内容只保留密钥一行，不加引号。然后编辑项目根目录的 `.env`，添加以下配置，把示例路径换成该文件的实际**绝对路径**：

```dotenv
CHESS_WORKBENCH_CCEF_PROVIDER_ENDPOINT=https://api.deepseek.com/chat/completions
CHESS_WORKBENCH_CCEF_PROVIDER_MODEL=deepseek-v4-flash
CHESS_WORKBENCH_CCEF_PROVIDER_API_KEY_FILE=/home/your-user/.config/chess-workbench/provider-api-key
```

`.env` 只保存密钥文件的路径，不要直接写 API 密钥。更换供应商时，endpoint 必须是完整的 Chat Completions 地址；其他供应商还需要兼容当前请求中的推理参数和输出额度，不能仅凭接口名称相同就保证可用。

### 安装棋盘图识别模型

```bash
make install-chess-diagram-model
```

它会将用于识别书中棋盘图的本地 ONNX 模型下载到 `data/models/chess-diagram/`。完成上述配置后重启后端，即可在“资料”页提交提取任务。

**纯扫描 PDF 另需 OCR。** 棋盘图模型不负责正文 OCR。带有可用文字层的 PDF 可以直接提取；没有文字层的页面需要另行提供兼容的 PaddleOCR runner，并设置 `CHESS_WORKBENCH_PADDLE_OCR_RUNNER_PATH`。仓库目前只有 [runner 接口适配器](backend/src/chess_workbench/extraction/paddleocr.py)，没有一键安装 OCR 服务的脚本。

## 数据保存、备份与更新

默认配置下，应用数据都在项目的 `data/` 目录：

| 路径 | 内容 |
| --- | --- |
| `data/database/` | SQLite 数据库，包括课程、棋谱和任务状态 |
| `data/sources/` | 上传的原始文件 |
| `data/derived/` | 提取过程中的页面、证据和模型响应等工件 |
| `data/review-revisions/` | 人工审核修订工件 |
| `data/engines/`、`data/models/` | 本地引擎和识别模型 |

备份时先停止后端，再复制**整个 `data/` 目录**，并单独保存 `.env` 和仓库外的密钥文件。只备份数据库会丢失它引用的原文件和提取工件。`data/` 和 `.env` 默认不进入 Git，推送代码不等于备份数据。

更新前先备份，然后在没有本地代码改动的情况下执行：

```bash
git pull --ff-only
make bootstrap
```

重新运行 `make dev-api` 和 `make dev-web`。后端启动时会执行新版本的数据库迁移；不要用 `.env.example` 覆盖已有 `.env`。

## 部署到自己的远程机器

上述命令也可以在自己的 Linux 服务器上运行。**当前没有用户登录和访问权限隔离**，默认只监听 `127.0.0.1`，适合个人使用。一个简单的远程使用方式是让服务保持本机监听，然后在自己电脑上通过 SSH 转发网页端口：

```bash
ssh -N -L 5173:127.0.0.1:5173 user@your-server
```

随后仍在自己电脑打开 `http://127.0.0.1:5173`，API 和 WebSocket 由服务器上的前端代理转发，不需要额外公开 8000 端口。服务器上的两个服务需要保持运行。

仓库暂未提供 Docker Compose 或生产环境的一键部署。若自行搭建公开站点，还需要访问控制，以及静态前端、`/api` 和 WebSocket 的反向代理配置；仅将 `frontend/dist/` 放到静态托管平台不能运行完整网站。

## 常见启动问题

| 现象 | 处理方式 |
| --- | --- |
| 找不到 `pnpm` / `uv` / `make` | 确认工具已安装并在当前终端的 PATH 中；Node.js 使用 22.x |
| 网页能打开，但读取数据失败 | 确认 `make dev-api` 仍在运行；可访问 `http://127.0.0.1:8000/api/health` 查看后端是否可用 |
| 8000 端口被占用 | 修改 `.env` 的 `CHESS_WORKBENCH_PORT`，同时修改 `CHESS_WORKBENCH_API_PROXY_TARGET`，然后重启前后端 |
| 5173 端口被占用 | 按前端终端输出的地址访问，或用 `pnpm --dir frontend dev --port 5174` 指定空闲端口 |
| 引擎不可用 | 确认可执行文件适合当前系统、有执行权限，路径正确，并在安装后重启后端 |
| 提取报 `provider_unconfigured` | 检查密钥文件配置、绝对路径和文件权限；修改后重启后端 |
| 提取报 `ocr_unavailable` | 当前页面需要 OCR，而本机未配置可用的 OCR runner |
| 提取任务一直排队 | 确认后端正在运行，且 `.env` 中 `CHESS_WORKBENCH_ENGINE_WORKER_ENABLED=true`；该开关也控制 PDF 后台任务 |

## 更多文档

- [项目说明](docs/chess-workbench-project-description.md)
- [当前开发计划](docs/development-plan.md)
- [当前 PDF 提取架构](docs/architecture/pdf-extraction-current.md)
- [架构概览](docs/architecture/overview.md)
- [开发约定](AGENTS.md)
