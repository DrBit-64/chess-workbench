# ChessWorkbench

一个单用户、本地优先的国际象棋学习网站。你可以导入 PGN、编辑和学习课程、用 Stockfish 分析局面，也可以从 PDF 棋书中提取棋谱，经人工审核后发布到课程，并继续追加后面的页段。

课程、原始文件和提取记录默认保存在自己的电脑上。PDF AI 提取需要调用外部模型，会将选定页段及续接所需的前文信息发送给配置的供应商，并产生 API 费用；不配置模型也可以使用课程和 PGN 等功能。

个人开局库和间隔复习的规划见[当前开发计划](docs/development-plan.md)。

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

### 2. 一键启动网站

在普通 Linux / WSL2 终端运行，无需打开 VSCode：

```bash
./start.sh
```

也可以运行 `make dev`。脚本会同时启动前后端，自动创建 / 升级数据库，并在当前终端显示两者的日志。等待前后端启动完成后，浏览器打开 Vite 输出的 **Local** 地址，默认是 **http://127.0.0.1:5173**；API 默认地址是 `http://127.0.0.1:8000`。

保留这一个终端即可；停止时按一次 **Ctrl+C**，脚本会同时关闭前后端及其子进程。如果其中一个服务启动失败或退出，另一个也会停止。以后再次使用仍运行 `./start.sh`，不需要重新复制 `.env`。从其他目录启动时，可以直接使用脚本的绝对路径。

需要分别调试时，仍可在两个终端运行 `make dev-api` 和 `make dev-web`。统一脚本要求 Bash 4.3 及以上和 `setsid`，常见 Linux / WSL2 环境已提供；5173 端口被占用时会报错退出。

前端会把 `/api` 请求和 WebSocket 连接转发给后端，无需单独配置跨域。

若要更换网页端口，在 `.env` 中设置 `CHESS_WORKBENCH_WEB_PORT=5210`，然后重新启动。`./start.sh` 和 `make dev-web` 都会读取该设置，后端端口无需一起更改。

### 3. 开始使用

- **学习**：创建书籍、章节和课程内容，导入 PGN，编辑棋谱和学习已有课程。
- **我的对局**：收录实战、写棋步评语、收藏局面，按标签或笔记回到原棋谱。
- **资料**：上传自己的 PDF，选择物理页码范围提取，在审核页修正棋谱，再批准并发布到课程；后续可以从下一页连续追加提取。需要先完成下面的模型配置。
- **引擎**：分析局面、查看变化，或与引擎对弈。需要先安装 Stockfish。

仓库不附带棋书或个人课程，首次启动没有示例书籍。PDF 页码从文件第一页算起，可能与书上印刷的页码不同。初次提取建议选择一个完整例局；后续增量提取可以续接跨页棋局。

### 收录并复盘自己的棋

打开「我的对局 → 收录棋谱」。粘贴 Lichess 或 Chess.com 已结束的公开对局链接，也可粘贴、上传 PGN 后勾选要保存的对局。若 Chess.com 无法从链接找到公开档案，填写任一参赛者的用户名和对局结束月份。通过「对局账号」可以选择起始日期，手动同步某个公开账号；关闭后再次同步会接续已保存的进度。重复导入带同一平台编号的对局会打开已有棋谱。

每张棋谱卡片显示实战主线的最终局面、双方对局时的等级分、时限和 Lichess 开局名。以前保存的棋谱也会显示这些信息。打开棋谱后，点任意一步即可在棋盘上查看局面，在棋谱上方查看电脑端引擎的评分和候选变化。点一条变化可展开完整着法。点「分析整盘」可为整条主线补齐走后评分，正数表示白优。批量分析期间请保持复盘页打开，也可暂停，之后用相同设置继续，已算过的局面会直接复用。

「我的棋谱」默认按对局时间从新到旧排列，可以切换为从旧到新，也可以按具体时限筛选，例如只看 5+3。没有对局日期的棋谱按导入时间排序。

复盘带有用时记录的棋谱时，棋盘两端的棋钟显示走完当前实战着法后双方的剩余时间，翻转棋盘时随棋手换边。棋谱顶部的「记录走棋」图标默认开启。点击棋子再点目标格，或将棋子拖到目标格，即可跟进已有着法或保存新变例。关闭记录可临时试走。右键棋步可提升、降低变招的优先级，设为主线，或从该步开始删除；手机可用棋谱中的棋步菜单。修改复盘顺序后，仍可从「下载原始 PGN」取回原谱。

走谱时可以写棋步评语，或一键收藏当前棋盘。如果想留下做决定之前的局面，使用棋步菜单的「收藏走这步之前」。「局面收藏」支持标签组合和中文关键词搜索。「回到收藏处」打开原谱，「查其他出现」还会找到从未加星的相同局面。访问同一工作站的电脑和手机可以接着整理这些笔记。

取消收藏后，再次加星可恢复原笔记。想彻底清除条目可使用「永久删除」；整盘棋可先归档，再在「已归档」中选择恢复或永久删除。进入收藏的「练习局面」可录制自己的答案变化，或使用已安装的 Stockfish 从该局面续弈。

### 手机上读棋书

手机和电脑打开同一个传统课程链接。横握时左侧固定棋盘，右侧阅读讲解；竖握时棋盘在上方。右上角的「原书」和「讲解」切换右侧面板，「更多阅读选项」打开章节目录或返回书架。底部可逐步走谱，在变例中可回到分岔处。有扫描页的章节支持翻页、放大和临时全屏；直接点讲解中的页码可定位来源。同一浏览器会记住这本书最近的章节、棋步和阅读位置。课程仍由正在运行的工作台提供。

支持网页全屏的手机浏览器会在「原书」旁显示全屏图标。点一下即可全屏阅读、走谱和查原书，再点一次回到原来的棋步。普通横屏浏览时，棋盘按浏览器工具栏展开时的可用高度排版。

手机阅读有棋盘的章节时，工作台默认向电脑上的 Stockfish 请求当前局面的推荐着法。箭头表示各条候选线路的第一步，棋盘右边的黑白评分条随局面更新。宽屏课程页打开「引擎分析」后也可以看到评分条。手机右上角「⋯」可以关闭局面分析，或选「分析当前章节」预先算好当前章节及其子节的局面。批量分析期间请保持阅读页打开，再次运行会跳过已保存的结果。引擎安装步骤见下方「启用本地引擎」。

用 Android 真机测试时，先在 Windows 浏览器确认 Vite 输出的 **Local** 地址可用，再连接已开启 USB 调试的手机。在桌面 Chrome 的 `chrome://inspect/#devices` 中启用端口转发，设备端口可固定填 `5173`，目标填电脑实际的网页地址。例如 `.env` 设置了 `CHESS_WORKBENCH_WEB_PORT=5210` 时，目标填 `127.0.0.1:5210`；使用默认端口时填 `127.0.0.1:5173`。随后在手机打开 `http://localhost:5173/learn`，手机端口不需要与电脑端口相同。其他手机也可通过自己的私有网络访问前端。

手机浏览器也可以从「资料」上传 PDF 或添加其他来源。点棋书下方的「管理提取结果」选择页段，或从已有提取记录的「操作」打开原文与审核。审核页在竖屏将棋盘放在上方，横屏放在左侧，点「棋谱与检查」或「原书扫描」切换内容。独立原文页可点「查看大图」打开完整扫描图。

### 棋盘标记与子力差

在宽屏课程页，拖动两条栏间分隔线可调整目录、棋盘和课程内容的宽度，浏览器会记住设置。双击任一分隔线恢复默认；分隔线获得焦点后，也可用左右方向键微调。

课程、PDF 审核和引擎页面的棋盘采用相同操作：

- **按下左键**立即选子并显示合法落点；移动超过 3px 后拖动，棋子保持原尺寸跟随指针。点击走棋和棋谱切换使用 120ms 的快档动画，拖放落子直接就位。
- **右键单击**画圈，**按住右键拖动**画箭头；也支持 Shift + 左键拖动。
- 默认绿色；Shift/Ctrl + 右键为红色，Alt + 右键为蓝色，两组修饰键同时使用为黄色。
- 重画同一个标记可取消；左键点击棋盘或按 Esc 可清除。走棋或切换局面后清空临时标记。
- 棋盘上、下方显示双方同类棋子相抵后多出的子力，优势方另显示净分差。后、车、象/马、兵分别按 9、5、3、1 分计算；翻转棋盘时两行随之交换位置。

交互规则参考 [Chessground 拖动源码](https://github.com/lichess-org/chessground/blob/master/src/drag.ts)和[绘制源码](https://github.com/lichess-org/chessground/blob/master/src/draw.ts)，动画时长采用 [Lichess 的快档设置](https://github.com/lichess-org/lila/blob/master/modules/pref/src/main/Pref.scala)，子力差参考 [Lichess 的当前局面算法](https://github.com/lichess-org/lila/blob/master/ui/lib/src/game/material.ts)。标记用于当前局面的临时分析。

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

## 可选：把课程发送到 Lichess 研讨

课程页顶部的 **所选章节发送到 Lichess** 按钮可以发送当前小节或整个章节。要把**整门课程**生成一个研讨，点击课程标题旁的 ⚙ 设置菜单，选择 **整门课程发送到 Lichess**。
发送前会列出完整顺序：课程中的每个一级章节先作为目录章，其小节紧随其后、保留原始标题，例如 `Chapter One`、`Introduction`、`Game 1`、`Theory`。没有棋谱的目录章为零棋步；若一级章节自身有棋谱，则保留在该章。确认后创建一个研讨并返回链接。

首次使用需要配置一次个人令牌：

1. 登录 [Lichess 个人令牌页面](https://lichess.org/account/oauth/token)，创建仅带 **`study:write`** 权限的令牌。
2. 将令牌单独一行保存到仓库外，例如 `~/.config/chess-workbench/lichess-token`，并设置 `chmod 600`。
3. 在项目 `.env` 中填写其绝对路径，重启后端：

```dotenv
CHESS_WORKBENCH_LICHESS_API_TOKEN_FILE=/home/your-user/.config/chess-workbench/lichess-token
```

令牌只由后端读取，不需要粘贴到网页。这个功能不依赖 DeepSeek，不消耗模型额度。

每次发送都会创建一个新的 **不公开列出（unlisted）** 研讨，持链接的人可以访问；可以在
Lichess 内另行修改可见性。主线、分支、起始 FEN、棋步标注和已批准的局部注释会随 PGN
导出；章节正文归入起始局面的文字注释。PDF、图片文件、原书定位和 Markdown 排版不会迁移。
没有棋谱的目录或小节仍会保留为空章节；其独立正文放在起始局面注释中。所选范围若完全没有棋步则不会创建研讨。

[官方 API](https://lichess.org/api#tag/Studies/operation/apiStudyImportPGN) 限制单研讨最多 64 章；
超出容量时请选择较小范围。两边后续修改不会自动同步。若导入不完整或网络结果不确定，
页面会保留已取得的研讨链接并提示检查，不会自动重发。

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

重新运行 `./start.sh`。后端启动时会执行新版本的数据库迁移；不要用 `.env.example` 覆盖已有 `.env`。

## 部署到自己的远程机器

上述命令也可以在自己的 Linux 服务器上运行。**当前没有用户登录和访问权限隔离**，默认只监听 `127.0.0.1`，适合个人使用。一个简单的远程使用方式是让服务保持本机监听，然后在自己电脑上通过 SSH 转发网页端口：

```bash
ssh -N -L 5173:127.0.0.1:5173 user@your-server
```

随后仍在自己电脑打开 `http://127.0.0.1:5173`，API 和 WebSocket 由服务器上的前端代理转发，不需要额外公开 8000 端口。服务器上的启动脚本需要保持运行。

仓库暂未提供 Docker Compose 或生产环境的一键部署。若自行搭建公开站点，还需要访问控制，以及静态前端、`/api` 和 WebSocket 的反向代理配置；仅将 `frontend/dist/` 放到静态托管平台不能运行完整网站。

## 常见启动问题

| 现象 | 处理方式 |
| --- | --- |
| 找不到 `pnpm` / `uv` / `make` | 确认工具已安装并在当前终端的 PATH 中；Node.js 使用 22.x |
| 网页能打开，但读取数据失败 | 检查启动终端的后端日志；可访问 `http://127.0.0.1:8000/api/health` 查看后端是否可用 |
| 8000 端口被占用 | 先确认是否已经运行了 `./start.sh`；它已包含后端，不需要再运行 `make dev-api`。确需更换后端端口时，同时修改 `.env` 的 `CHESS_WORKBENCH_PORT` 和 `CHESS_WORKBENCH_API_PROXY_TARGET` |
| 网页端口被占用 | 统一脚本会报错退出；先关闭原来的网站再启动。也可通过 `.env` 的 `CHESS_WORKBENCH_WEB_PORT` 指定空闲端口 |
| WSL 内能访问，Windows 浏览器却拒绝连接 | 在 Windows PowerShell 中运行 `netsh interface ipv4 show excludedportrange protocol=tcp`；若网页端口落在系统保留范围内，在 `.env` 中选择范围外的 `CHESS_WORKBENCH_WEB_PORT`（例如 5210）并重启。还需确认 Windows 用户目录的 `.wslconfig` 未禁用 `localhostForwarding`；参见 [WSL 网络说明](https://learn.microsoft.com/en-us/windows/wsl/networking) |
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
