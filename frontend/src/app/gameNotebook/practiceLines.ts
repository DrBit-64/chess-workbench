import { Chess } from 'chess.js';
import type { ReviewNode } from './reviewTypes';

function playUci(board: Chess, uci: string) {
  return board.move({
    from: uci.slice(0, 2),
    to: uci.slice(2, 4),
    promotion: uci[4],
  });
}

export function positionAfter(fen: string, moves: string[]) {
  const board = new Chess(fen);
  for (const move of moves) playUci(board, move);
  return board;
}

export function lineNotation(fen: string, moves: string[]) {
  const board = new Chess(fen);
  return moves
    .map((uci, index) => {
      const [, side, , , , number] = board.fen().split(' ');
      const prefix =
        side === 'w' ? number + '. ' : index === 0 ? number + '... ' : '';
      return prefix + playUci(board, uci).san;
    })
    .join(' ');
}

export function parseAnswerLines(fen: string, input: string) {
  const lines = input
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length) throw Error('请录入至少一条答案变化。');
  return lines.map((line, index) => {
    const board = new Chess(fen);
    const tokens = line
      .replace(/\b\d+\.(?:\.\.)?/g, ' ')
      .trim()
      .split(/\s+/);
    return tokens.map((token) => {
      try {
        const move = /^[a-h][1-8][a-h][1-8][qrbn]?$/.test(token)
          ? playUci(board, token)
          : board.move(token);
        return move.from + move.to + (move.promotion ?? '');
      } catch {
        throw Error(`第 ${index + 1} 条答案中“${token}”不是此处的合法走法。`);
      }
    });
  });
}

/** Keep every authored alternative still consistent with what was actually played. */
export function advanceAnswer(
  lines: string[][],
  played: string[],
  move: string,
) {
  const next = [...played, move];
  const matching = lines.filter((line) =>
    next.every((uci, i) => line[i] === uci),
  );
  if (matching.length === 0) return null;
  if (matching.some((line) => line.length === next.length))
    return { moves: next, finished: true };
  const replies = Array.from(
    new Set(matching.map((line) => line[next.length])),
  );
  const reply = replies[Math.floor(Math.random() * replies.length)];
  const moves = [...next, reply];
  return {
    moves,
    finished: matching.some(
      (line) => line.length === moves.length && line[next.length] === reply,
    ),
  };
}

/** A training answer follows the played game even after its review variations are reordered. */
export function bookmarkContinuation(
  nodes: ReviewNode[],
  anchorId: string,
  related: { node_id: string }[],
) {
  const byParent = new Map<string, ReviewNode[]>();
  for (const node of nodes) {
    if (!node.parent_id) continue;
    const children = byParent.get(node.parent_id) ?? [];
    children.push(node);
    byParent.set(node.parent_id, children);
  }
  const linked = new Set(related.map((item) => item.node_id));
  let parent = nodes.find((node) => node.id === anchorId);
  const moves: string[] = [];
  while (parent && moves.length < 5) {
    const children = byParent.get(parent.id) ?? [];
    const explicit =
      !moves.length && children.find((node) => linked.has(node.id));
    const next: ReviewNode | undefined =
      explicit ||
      (parent.is_mainline
        ? children.find((node) => node.is_mainline)
        : children
            .filter((node) => !node.hidden)
            .sort((a, b) => a.sort_order - b.sort_order)[0]);
    if (!next?.uci) break;
    moves.push(next.uci);
    parent = next;
  }
  return moves;
}
