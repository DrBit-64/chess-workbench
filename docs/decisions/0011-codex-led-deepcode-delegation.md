# ADR 0011：Codex 主控的 DeepCode 有界任务委派

- 状态：已接受
- 日期：2026-08-11

## 背景

项目此前由 Codex 设计、审查，DeepCode（DeepSeek V4 Flash）执行部分小任务，但需要用户在两个
聊天窗口之间手工复制任务和完成报告。一个候选方案是在 `.agent-sync/` 中维护 Codex 与 DeepCode
各自的 handoff 文件，再用 Codex Hooks 和 DeepCode `notify` 相互注入。该方案能同步上下文，却仍
要求用户切换到 DeepCode 窗口触发下一步，而且容易形成两个都能继续派活的对等控制面。

本项目需要的是另一种拓扑：用户只与 Codex 对话；Codex 决定任务边界、调用低成本工作模型、审查
实际改动，并在复杂故障时直接接管。

本机 DeepCode CLI 0.1.34 即使提供 `--prompt` 仍要求 stdin 是 TTY，且完成通知以分离进程执行，
因此普通的重定向式无头命令不是可靠控制接口。

## 决定

采用 Codex 主控、DeepCode 一次性执行的有界委派：

1. `PLANS.md` 是任务输入。每个可委派任务必须先成为具名 packet，明确文件边界、行为、不变量、
   验收命令和停止条件。
2. 项目技能 `$delegate-deepcode` 是唯一自动委派入口。启动器为 DeepCode 分配私有 PTY，持有单实例
   文件锁，并注入不可猜测的 run ID 和专用结果目录。
3. `.deepcode/settings.json` 的 `notify` 只在启动器提供 run ID 时原子写入该 run 的 `result.json`；
   用户手工开启的 DeepCode 会话不会写入委派结果。
4. 运行 prompt、基线 Git 状态、终端记录和通知位于 gitignored 的
   `.agent-sync/runs/<run-id>/`。它们只用于传输和诊断，不是长期项目记忆。
5. DeepCode 在工作区内只获得读、写和 Git 历史查询能力。删除、修改 Git 历史、工作区外访问、
   工具网络和 MCP 均拒绝，避免无人值守任务停在权限询问或扩大作用域。
6. Codex 在同一轮中等待完成，随后检查真实 diff 并独立执行聚焦验收。DeepCode 不得批准自己的
   结果，也不得提交代码。
7. 根因不清、公共接口或架构决策、数据库/协议/安全变更、跨无关模块修复，以及同一修正失败两次
   的任务由 Codex 直接处理。

不把 Codex `Stop`/`UserPromptSubmit` 双向文件总线作为核心控制机制。Hooks 未来可以用于审计或
附加只读上下文，但不能产生第二个调度者。

## 后果

正面影响：

- 用户只需保持与 Codex 的一条对话；任务启动、完成回传和复审均自动化。
- V4 Flash 承担已设计的机械实现，Codex 额度集中在设计、反例审查和复杂修复。
- 每次运行有互斥锁、基线状态和独立记录，减少并发编辑及错误归因。
- 即使通知失败或超时，Git 工作区和终端记录仍可恢复、检查。

代价与限制：

- 启动器依赖 Linux/WSL 的 PTY 和 `fcntl`，当前不承诺原生 Windows 支持。
- DeepCode CLI 没有稳定的机器可读无头协议；升级 CLI 后需要重新验证 PTY 与 `notify` 行为。
- 文件锁只能约束通过启动器发起的任务。委派期间仍不应手工启动另一个 DeepCode 实例编辑同一仓库。
- Codex 的独立复审仍会消耗一定额度；这是保证复杂缺陷由 Codex 保底所需的成本。
