# ADR 0002：标准棋局面身份与完整状态分离

- 状态：Accepted
- 日期：2026-08-06

## 背景

ChessWorkbench 需要把不同着序到达的同一局面合并为一个知识节点，同时仍要保留 PGN
回放、五十回合规则和后续 Syzygy 判定所需的完整状态。直接以六字段 FEN 作为唯一键会让
只差钟数的局面无法共享知识；只保存归一化局面又会丢失对局语义。

python-chess 的私有 transposition tuple 和 64 位 Zobrist 值都不作为持久化契约：前者没有
稳定 API 保证，后者存在碰撞且不可直接审计。

## 决定

### 输入范围

- Stage 2A 只支持标准国际象棋，不支持 Chess960 或其他变体；
- 输入必须是六字段 FEN；
- 不接受 Shredder-FEN 易位列字母或 python-chess 的 `~` 升变来源扩展；
- FEN 必须通过 python-chess 的标准棋结构合法性检查；不额外证明该局面在历史上可达；
- 解析或结构验证失败转换为具有稳定机器码的领域错误，不向 API 暴露依赖库异常文本。

### 两种表示

`PositionState.full_fen` 是经过 python-chess 规范化的六字段 FEN：

- 保留半回合钟和回合数；
- 保留输入中规则允许的原始 en-passant 目标格，即使当前没有棋子能够合法吃过路兵；
- 用于对局 occurrence、练习起始状态、PGN 回放和棋步计算。

`PositionState.canonical_fen` 表示知识图身份：

```text
<piece-placement> <side-to-move> <castling-rights> <legal-en-passant> 0 1
```

其中：

- 棋子布局与行棋方必须相同；
- 易位权使用经过标准棋合法性检查的 `KQkq` 子集，无权时为 `-`；
- 只有当前存在**合法**吃过路兵时才保留目标格；伪合法但因王被将而不能走也视为 `-`；
- 半回合钟和回合数固定为 `0 1`，不参与知识节点去重。

持久化 `position_key` 的首版格式为：

```text
standard:v1:<canonical-fen 的前四字段>
```

键显式包含标准棋 variant namespace 和格式版本，且是无损、可审计的规范文本，不使用
单独的短哈希作为唯一事实。未来若加入 Chess960/其他 variant 或规则变化，必须使用独立
namespace/新版本并提供迁移，不能静默改变 `standard:v1` 的含义。

### 棋步与衍生字段

- 持久化棋步只接受标准、小写 UCI；
- python-chess 从 `full_fen` 权威验证合法性，在走子前生成 SAN，并产生目标完整 FEN；
- `MoveResult` 同时携带 UCI、SAN、走子前和走子后的不可变 `PositionState`；
- `material_signature` 使用带版本、按双方 `KQRBNP` 计数的稳定字符串，只作匹配/筛选，
  不参与 position identity。

## 示例

以下两个完整 FEN 共享同一 `position_key`，但 `full_fen` 不同：

```text
8/8/8/8/8/4k3/8/4K3 w - - 0 1
8/8/8/8/8/4k3/8/4K3 w - - 99 73
```

`1. e4` 后的原始 en-passant 格 `e3` 保留在 `full_fen`，但黑方没有合法吃子，因此规范
身份中的 en-passant 为 `-`。如果白兵在 e5、黑兵刚到 d5 且 `exd6 e.p.` 合法，`d6`
进入规范身份；若白兵被钉住使该步非法，则仍归一化为 `-`。

## 后果

- 转置和只差钟数的课程内容可共享知识节点；
- 对局、练习和残局仍能保留五十回合规则所需的完整状态；
- 相同棋盘但行棋方、易位权或合法 en-passant 不同的状态不会被错误合并；
- 三次重复依赖路径历史，不能仅凭 `position_key` 判断；
- 数据层必须对 `position_key` 建唯一约束，并把完整状态放在 occurrence 或等价上下文中；
- 全局图允许循环，遍历 API 必须携带路径语境并限制深度和节点数。
