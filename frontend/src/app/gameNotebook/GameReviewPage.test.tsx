import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { Chess, type Square } from 'chess.js';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { SWRConfig } from 'swr';
import { expect, it, vi } from 'vitest';

import { GameReviewPage } from './GameReviewPage';
import type { ReviewBookmark, ReviewGame, ReviewNode } from './reviewTypes';

vi.mock('../../components/WorkbenchBoard', () => ({
  WorkbenchBoard: ({
    position,
    onSquareClick,
  }: {
    position: string;
    onSquareClick: (square: Square) => void;
  }) => (
    <>
      <div aria-label="测试棋盘">{position}</div>
      <button onClick={() => onSquareClick('d7')}>d7</button>
      <button onClick={() => onSquareClick('d5')}>d5</button>
    </>
  ),
}));

function exampleGame() {
  const root: ReviewNode = {
    id: 'root',
    parent_id: null,
    ply: 0,
    sort_order: 0,
    is_mainline: true,
    hidden: false,
    fen: 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 24',
    san: null,
    uci: null,
    nags: [],
    starting_comment: '',
    comment: '',
    note: '',
    version: 1,
  };
  const main: ReviewNode = {
    ...root,
    id: 'c5',
    parent_id: 'root',
    ply: 1,
    uci: 'c7c5',
    san: 'c5',
    fen: 'rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 25',
  };
  const reply: ReviewNode = {
    ...main,
    id: 'Nf3',
    parent_id: 'c5',
    ply: 2,
    uci: 'g1f3',
    san: 'Nf3',
    fen: 'rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 25',
  };
  const alternative: ReviewNode = {
    ...main,
    id: 'e5',
    is_mainline: false,
    sort_order: 1,
    uci: 'e7e5',
    san: 'e5',
    fen: 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 25',
  };
  const game: ReviewGame = {
    id: 'game',
    white: 'A',
    black: 'B',
    date: '2026.11.07',
    result: '*',
    platform: null,
    source_url: null,
    summary: '',
    archived_at: null,
    created_at: '2026-11-07T00:00:00Z',
    version: 1,
    headers: {},
    nodes: [root, main, reply, alternative],
  };
  return { game, root, main, reply, alternative };
}

it('replays a black-to-move fragment and adds the arriving move to a bookmark originally made for its continuation', async () => {
  const { game, root, main, reply } = exampleGame();
  const bookmark: ReviewBookmark = {
    id: 'bookmark',
    game_id: game.id,
    node_id: main.id,
    white: 'A',
    black: 'B',
    date: game.date,
    ply: 1,
    fen: main.fen,
    san: main.san,
    is_mainline: true,
    archived: false,
    title: '',
    note: '',
    tags: [],
    active: true,
    version: 1,
    created_at: game.created_at,
    related_moves: [{ node_id: reply.id, san: 'Nf3', note: '' }],
    matches: [],
  };
  const onStar = vi.fn();
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async (input, options) => {
      const path = String(input);
      if (path.endsWith('/games/game')) return Response.json(game);
      if (path.includes('/bookmarks?game_id=game'))
        return Response.json({ items: [bookmark], total: 1 });
      if (path.endsWith('/bookmarks') && options?.method === 'POST') {
        onStar(JSON.parse(options.body as string));
        return Response.json({
          ...bookmark,
          version: 2,
          related_moves: [
            ...bookmark.related_moves,
            { node_id: main.id, san: main.san, note: '' },
          ],
        });
      }
      throw new Error('Unexpected request ' + path);
    });
  renderReview('/games/game?node=e5');
  const line = await screen.findByRole('button', {
    name: '24... e5，分析变例',
  });
  expect(line.getAttribute('aria-current')).toBe('step');
  fireEvent.click(screen.getByRole('button', { name: '上一步' }));
  expect(screen.getByLabelText('测试棋盘').textContent).toBe(root.fen);
  fireEvent.keyDown(window, { key: 'ArrowRight' });
  expect(line.getAttribute('aria-current')).toBe('step');

  fireEvent.click(screen.getByRole('button', { name: '24... c5，已收藏' }));
  fireEvent.click(screen.getByRole('button', { name: '棋步菜单' }));
  fireEvent.click(
    await screen.findByRole('menuitem', { name: '关联刚走的棋步' }),
  );
  await waitFor(() =>
    expect(onStar).toHaveBeenCalledWith({
      node_id: 'c5',
      related_node_id: 'c5',
    }),
  );
  expect(screen.getByLabelText('测试棋盘').textContent).toBe(main.fen);
  fetchMock.mockRestore();
});

function renderReview(entry: string) {
  render(
    <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/games/:gameId" element={<GameReviewPage />} />
        </Routes>
      </MemoryRouter>
    </SWRConfig>,
  );
}

it('keeps a newer selection while a recorded move is saving and can revisit that variation after the response', async () => {
  const { game, root, main, alternative } = exampleGame();
  const board = new Chess(root.fen);
  const d5 = board.move('d5');
  const branch = {
    ...alternative,
    id: 'd5',
    uci: d5.lan,
    fen: d5.after,
    san: d5.san,
    sort_order: 2,
  };
  let finish!: () => void;
  const posted = vi.fn();
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async (input, options) => {
      const path = String(input);
      if (path.endsWith('/games/game')) return Response.json(game);
      if (path.includes('/bookmarks?'))
        return Response.json({ items: [], total: 0 });
      if (path.endsWith('/games/game/moves')) {
        posted(JSON.parse(options?.body as string));
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        return Response.json({
          game_version: 2,
          selected_id: 'd5',
          nodes: [branch],
        });
      }
      throw new Error('Unexpected request ' + path);
    });
  try {
    renderReview('/games/game');
    await screen.findByRole('button', { name: 'd7' });
    fireEvent.click(screen.getByRole('button', { name: 'd7' }));
    fireEvent.click(screen.getByRole('button', { name: 'd5' }));
    expect(posted).toHaveBeenCalledWith({
      expected_version: 1,
      parent_id: 'root',
      uci: 'd7d5',
    });
    expect(screen.getByLabelText('测试棋盘').textContent).toBe(branch.fen);
    fireEvent.click(screen.getByRole('button', { name: '24... c5' }));
    await act(async () => {
      finish();
    });
    const newMove = await screen.findByRole('button', {
      name: '24... d5，分析变例',
    });
    expect(screen.getByLabelText('测试棋盘').textContent).toBe(main.fen);
    fireEvent.click(newMove);
    expect(screen.getByLabelText('测试棋盘').textContent).toBe(branch.fen);
  } finally {
    fetchMock.mockRestore();
  }
});
