import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Chess } from 'chess.js';
import { SWRConfig } from 'swr';
import { afterEach, expect, it, vi } from 'vitest';
import { GameReviewEnginePanel } from './GameReviewEnginePanel';
import {
  reviewAnalysisPositions,
  useGameReviewEngine,
} from './useGameReviewEngine';
import type { ReviewGame } from './reviewTypes';

const chess = new Chess();
const fens = [chess.fen()];
for (const san of ['e4', 'e5', 'Nf3']) {
  chess.move(san);
  fens.push(chess.fen({ forceEnpassantSquare: true }));
}
const game = {
  id: 'game',
  nodes: fens.map((fen, i) => ({
    id: String(i),
    parent_id: i > 0 ? String(i - 1) : null,
    fen,
    is_mainline: true,
    comment: i === 2 ? '[%eval #-3,12]' : '',
  })),
} as ReviewGame;

function TestPage({ active = 1 }: { active?: number }) {
  const engine = useGameReviewEngine(game, game.nodes[active]);
  return (
    <>
      <GameReviewEnginePanel analysis={engine} />
      <output aria-label="scores">
        {[...engine.scores]
          .sort()
          .map(([id, text]) => id + ':' + text)
          .join(' ')}
      </output>
    </>
  );
}
function json(value: unknown) {
  return new Response(JSON.stringify(value), {
    headers: { 'content-type': 'application/json' },
  });
}
afterEach(() => vi.unstubAllGlobals());

it('includes the promoted continuation alongside the played game and removes deleted continuations from the batch', () => {
  const board = new Chess(fens[1]);
  board.move('c5');
  const promoted = {
    ...game.nodes[2],
    id: 'c5',
    fen: board.fen(),
    sort_order: 0,
    is_mainline: false,
  };
  const movedDown = { ...game.nodes[2], sort_order: 1 };
  const hidden = { ...game.nodes[3], hidden: true };
  const plan = reviewAnalysisPositions([
    game.nodes[0],
    game.nodes[1],
    movedDown,
    hidden,
    promoted,
  ]);
  expect(plan.fens).toContain(promoted.fen);
  expect(plan.fens).toContain(movedDown.fen);
  expect(plan.fens).not.toContain(hidden.fen);
});

it('restores White scores, numbers Black PVs, and resumes an interrupted game using the saved analyses', async () => {
  const stored = new Set(fens.slice(0, 1));
  const computed: string[] = [];
  let fail = true;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/engine/capabilities')
        return json({
          available: true,
          engine_name: 'Stockfish',
          syzygy_available: false,
        });
      const body = JSON.parse(String(init?.body ?? '{}')) as {
        fen?: string;
        fens?: string[];
      };
      if (url.endsWith('cache-lookup'))
        return json({
          cached_fens: body.fens!.filter((fen) => stored.has(fen)),
          missing_fens: body.fens!.filter((fen) => !stored.has(fen)),
          cached_scores: body
            .fens!.filter((fen) => stored.has(fen))
            .map((fen) => ({ fen, score_cp: 45, mate: null, wdl: null })),
        });
      if (url === '/api/engine/analyses') {
        const fen = body.fen!;
        if (fail && fen === fens[3]) throw Error('网络中断');
        stored.add(fen);
        computed.push(fen);
        return json({
          id: fen,
          fen,
          engine_name: 'Stockfish',
          depth: 14,
          lines: [
            {
              rank: 1,
              score_cp: 45,
              mate: null,
              wdl: null,
              san: ['e5', 'Nf3', 'Nc6'],
              uci: ['e7e5', 'g1f3', 'b8c6'],
            },
          ],
        });
      }
      throw Error('unexpected url ' + url);
    }),
  );
  render(
    <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}>
      <TestPage />
    </SWRConfig>,
  );
  await screen.findByText('1... e5 2. Nf3 Nc6');
  await waitFor(() =>
    expect(screen.getByLabelText('scores').textContent).toContain(
      '0:+0.45 1:+0.45 2:#-3',
    ),
  );
  fireEvent.click(screen.getByRole('button', { name: '分析整盘棋谱' }));
  await screen.findByText(/分析中断，可重试/);
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: '分析整盘棋谱' }));
  await screen.findByText(/整盘分析已完成/);
  expect(computed).toEqual([fens[1], fens[2], fens[3]]);
  expect(screen.getByLabelText('scores').textContent).toContain(
    '2:+0.45 3:+0.45',
  );
});
