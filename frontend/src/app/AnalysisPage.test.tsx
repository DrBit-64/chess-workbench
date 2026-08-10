import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { SWRConfig } from 'swr';
import { describe, expect, it, vi } from 'vitest';

import { AnalysisPage } from './AnalysisPage';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  close = vi.fn();

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }
}

vi.mock('react-chessboard', () => ({
  Chessboard: ({
    position,
    onPieceDrop,
    onPieceDragBegin,
    onPieceDragEnd,
    onSquareClick,
  }: {
    position: string;
    onPieceDrop: (source: string, target: string) => boolean;
    onPieceDragBegin: (piece: unknown, source: string) => void;
    onPieceDragEnd: () => void;
    onSquareClick: (square: string) => void;
  }) => (
    <div aria-label="测试分析棋盘">
      <span data-testid="board-position">{position}</span>
      <button onClick={() => onPieceDrop('e2', 'e4')}>模拟拖放 e2e4</button>
      <button onClick={() => onPieceDragBegin(undefined, 'e2')}>
        模拟拖动开始
      </button>
      <button onClick={onPieceDragEnd}>模拟拖动结束</button>
      <button onClick={() => onSquareClick('e2')}>模拟点击 e2</button>
      <button onClick={() => onSquareClick('e4')}>模拟点击 e4</button>
    </div>
  ),
}));

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

const capabilities = {
  available: true,
  engine_path: '/data/stockfish',
  engine_name: 'Stockfish 18',
  engine_version: '18',
  syzygy_available: false,
  syzygy_path: '/data/syzygy',
  default_parameters: {
    multipv: 4,
    movetime_ms: 800,
    depth: null,
    threads: 1,
    hash_mb: 128,
    ponder: false,
  },
  max_threads: 4,
  max_hash_mb: 1024,
  max_time_ms: 30000,
  time_presets_ms: [500, 800, 2000, 4000],
  multipv_max: 5,
  install_hint: null,
};

const analysis = {
  id: 'analysis-1',
  fen: 'start',
  source: 'engine',
  engine_name: 'Stockfish',
  engine_version: '18',
  parameters: capabilities.default_parameters,
  lines: [
    ['e4', 34],
    ['d4', 27],
    ['Nf3', 18],
    ['c4', 12],
  ].map(([san, score], index) => ({
    rank: index + 1,
    score_cp: score,
    mate: null,
    wdl: [400, 500, 100],
    uci: [['e2e4', 'd2d4', 'g1f3', 'c2c4'][index]],
    san: [san],
  })),
  depth: 16,
  seldepth: 22,
  nodes: 120000,
  elapsed_ms: 800,
  from_cache: false,
  created_at: '2026-08-10T00:00:00Z',
};

const game = {
  id: '00000000-0000-4000-8000-000000000006',
  version: 1,
  initial_fen: START_FEN,
  current_fen: START_FEN,
  user_color: 'white',
  strength: 5,
  status: 'active',
  result: null,
  engine_name: 'Stockfish',
  engine_version: '18',
  moves: [],
  created_at: '2026-08-10T00:00:00Z',
  updated_at: '2026-08-10T00:00:00Z',
};

const gameAfterMove = {
  ...game,
  version: 2,
  current_fen: 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2',
  moves: [
    {
      ply: 1,
      actor: 'user',
      before_fen: START_FEN,
      after_fen: 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1',
      uci: 'e2e4',
      san: 'e4',
    },
    {
      ply: 2,
      actor: 'engine',
      before_fen: 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1',
      after_fen: 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2',
      uci: 'e7e5',
      san: 'e5',
    },
  ],
};

function renderPage() {
  return render(
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      <AnalysisPage />
    </SWRConfig>,
  );
}

describe('Stage 6 engine workspace', () => {
  it('requests and renders four scored principal variations', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      init?.method === 'POST' ? json(analysis) : json(capabilities),
    );
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /^分\s*析$/ }));
    expect(await screen.findByText('e4')).toBeTruthy();
    expect(screen.getByText('d4')).toBeTruthy();
    expect(screen.getByText('Nf3')).toBeTruthy();
    expect(screen.getByText('c4')).toBeTruthy();
    expect(screen.getAllByText('+0.34')).toHaveLength(2);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/engine/analyses',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"multipv":4'),
        }),
      ),
    );
  });

  it('exposes Lichess-shaped time, lines, threads, hash and ponder settings', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(capabilities)),
    );
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /设\s*置/ }));
    expect(await screen.findByText('搜索时间')).toBeTruthy();
    expect(screen.getByLabelText('分析引擎')).toBeTruthy();
    expect(screen.getByText('线路：4')).toBeTruthy();
    expect(screen.getByText('线程：1')).toBeTruthy();
    expect(screen.getByText('内存：128 MB')).toBeTruthy();
    expect(screen.getByText('Ponder 关闭')).toBeTruthy();
  });

  it('makes a missing local engine actionable instead of fabricating analysis', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        json({
          ...capabilities,
          available: false,
          engine_name: null,
          engine_version: null,
          install_hint: 'run make install-stockfish',
        }),
      ),
    );
    renderPage();
    expect(await screen.findByText('尚未安装 Stockfish')).toBeTruthy();
    expect(screen.getByText(/make install-stockfish/)).toBeTruthy();
    expect(
      screen
        .getByRole('button', { name: /^分\s*析$/ })
        .hasAttribute('disabled'),
    ).toBe(true);
  });

  it('loads FEN, moves on the board, and can cancel a durable background job', async () => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    const queued = {
      id: '00000000-0000-4000-8000-000000000060',
      kind: 'engine_analysis',
      status: 'queued',
      payload: {},
      result: null,
      attempt_count: 0,
      max_attempts: 3,
      cancel_requested_at: null,
      last_error_code: null,
      last_error_message: null,
      created_at: '2026-08-10T00:00:00Z',
      updated_at: '2026-08-10T00:00:00Z',
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/cancel'))
        return json({ ...queued, status: 'cancelled' });
      if (url === '/api/engine/analysis-jobs') return json(queued, 202);
      if (url.startsWith('/api/jobs/')) return json(queued);
      if (init?.method === 'POST') return json(analysis);
      return json(capabilities);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    const fenInput = await screen.findByLabelText('分析局面 FEN');
    fireEvent.change(fenInput, {
      target: { value: '8/8/8/8/8/8/4K3/6k1 w - - 0 1' },
    });
    fireEvent.click(screen.getByRole('button', { name: '载入 FEN' }));
    expect(screen.getByTestId('board-position').textContent).toContain('4K3');

    fireEvent.change(fenInput, { target: { value: START_FEN } });
    fireEvent.click(screen.getByRole('button', { name: '载入 FEN' }));
    fireEvent.click(screen.getByRole('button', { name: '模拟拖动开始' }));
    fireEvent.click(screen.getByRole('button', { name: '模拟拖动结束' }));
    fireEvent.click(screen.getByRole('button', { name: '模拟点击 e2' }));
    fireEvent.click(screen.getByRole('button', { name: '模拟点击 e4' }));
    await waitFor(() =>
      expect(screen.getByTestId('board-position').textContent).toContain('4P3'),
    );

    fireEvent.click(screen.getByRole('button', { name: '后台深度分析' }));
    const cancel = await screen.findByRole('button', {
      name: '取消后台分析',
    });
    expect(FakeWebSocket.instances[0]?.url).toContain('/api/invalidations/ws');
    act(() => {
      FakeWebSocket.instances[0]?.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            resource_type: 'job',
            resource_id: queued.id,
          }),
        }),
      );
      FakeWebSocket.instances[0]?.onmessage?.(
        new MessageEvent('message', { data: 'not-json' }),
      );
    });
    fireEvent.click(cancel);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/jobs/${queued.id}/cancel`,
        expect.objectContaining({ method: 'POST' }),
      ),
    );
  });

  it('plays from the position and turns the game into review findings', async () => {
    const review = {
      game_id: game.id,
      findings: [
        {
          ply: 1,
          fen: START_FEN,
          played_uci: 'e2e4',
          best_uci: 'e2e4',
          loss_cp: 0,
          verdict: 'best',
          explanation: 'best',
        },
      ],
      analyzed_positions: 1,
      created_at: '2026-08-10T00:00:00Z',
    };
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/moves')) return json(gameAfterMove);
        if (url.endsWith('/review')) return json(review);
        if (url === '/api/engine/games' && init?.method === 'POST')
          return json(game, 201);
        return json(capabilities);
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByText('指定局面对弈'));
    fireEvent.click(screen.getByRole('radio', { name: '黑方' }));
    fireEvent.click(screen.getByRole('radio', { name: '白方' }));
    fireEvent.click(screen.getByRole('button', { name: '从当前局面开始' }));
    expect(await screen.findByText('强度 5/8')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '模拟拖放 e2e4' }));
    expect(await screen.findByText('2. e5')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '复盘我的决策' }));
    expect(await screen.findByText(/第 1 ply/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '新对局' }));
    expect(
      await screen.findByRole('button', { name: '从当前局面开始' }),
    ).toBeTruthy();
  });

  it('uses the accessible success treatment for a finished game', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input) === '/api/engine/games' && init?.method === 'POST') {
          return json({ ...game, status: 'finished', result: '1-0' }, 201);
        }
        return json(capabilities);
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByText('指定局面对弈'));
    fireEvent.click(screen.getByRole('button', { name: '从当前局面开始' }));

    expect(
      (await screen.findByText('finished')).classList.contains(
        'analysis-success-tag',
      ),
    ).toBe(true);
  });
});
