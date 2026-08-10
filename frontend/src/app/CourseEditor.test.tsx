import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { SWRConfig } from 'swr';
import { describe, expect, it, vi } from 'vitest';

import { CourseEditor } from './CourseEditor';

vi.mock('react-chessboard', () => ({
  Chessboard: ({
    position,
    onPieceDrop,
    onSquareClick,
    animationDuration,
    customSquareStyles,
    customArrows = [],
  }: {
    position: string;
    onPieceDrop: (source: string, target: string) => boolean;
    onSquareClick: (square: string) => void;
    animationDuration: number;
    customSquareStyles: Record<string, Record<string, string | number>>;
    customArrows?: unknown[];
  }) => (
    <div aria-label="测试棋盘">
      <span>{position}</span>
      <output
        data-testid="board-feedback"
        data-animation-duration={animationDuration}
      >
        {JSON.stringify(customSquareStyles)}
      </output>
      <output data-testid="board-arrows">{JSON.stringify(customArrows)}</output>
      <button onClick={() => onSquareClick('e2')}>选择 e2</button>
      <button onClick={() => onPieceDrop('e2', 'e4')}>走 e4</button>
      <button onClick={() => onPieceDrop('g1', 'f3')}>走 Nf3</button>
      <button onClick={() => onPieceDrop('e2', 'e5')}>走非法棋步</button>
    </div>
  ),
}));

const startFen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const e4Fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1';

const course = {
  id: 'course-1',
  title: '可交互课程',
  description: null,
  mode: 'traditional',
  status: 'draft',
  tags: [],
  version: 1,
  archived_at: null,
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
};
const module = {
  id: 'module-1',
  course_id: 'course-1',
  parent_id: null,
  title: '第一章',
  sort_order: 0,
  start_position_id: 'position-1',
  version: 1,
  archived_at: null,
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
};
const root = {
  id: 'occ-root',
  module_id: 'module-1',
  parent_id: null,
  position_id: 'position-1',
  move_edge_id: null,
  sort_order: 0,
  nag: null,
  comment_before: null,
  comment_after: null,
  is_mainline: true,
  version: 1,
  archived_at: null,
  full_fen: startFen,
  inbound_uci: null,
  inbound_san: null,
};
const e4 = {
  ...root,
  id: 'occ-e4',
  parent_id: 'occ-root',
  position_id: 'position-e4',
  move_edge_id: 'move-e4',
  full_fen: e4Fen,
  inbound_uci: 'e2e4',
  inbound_san: 'e4',
};
const e5 = {
  ...e4,
  id: 'occ-e5',
  parent_id: 'occ-e4',
  position_id: 'position-e5',
  move_edge_id: 'move-e5',
  full_fen: 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2',
  inbound_uci: 'e7e5',
  inbound_san: 'e5',
};
const nf3 = {
  ...e5,
  id: 'occ-nf3-line',
  parent_id: 'occ-e5',
  position_id: 'position-nf3',
  move_edge_id: 'move-nf3',
  full_fen: 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2',
  inbound_uci: 'g1f3',
  inbound_san: 'Nf3',
};
const transposedRoot = { ...root, id: 'occ-transposed' };
const note = {
  id: 'note-1',
  version: 1,
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
  archived_at: null,
  target: { kind: 'occurrence', occurrence_id: 'occ-root' },
  source_note_id: null,
  note_type: 'general',
  markdown: 'Initial explanation',
  source_span_ids: ['span-1'],
  review_status: 'approved',
  rendered_markdown: 'Initial explanation',
  rendered_source_span_ids: ['span-1'],
  source_course_id: 'course-1',
  source_module_id: 'module-1',
  source_occurrence_id: 'occ-root',
};
const citableSource = {
  source: { id: 'source-1', title: 'Source One' },
  source_version: { id: 'version-1' },
  source_span: { id: 'span-1', locator: { kind: 'whole' } },
};

const engineCapabilities = {
  available: true,
  engine_path: '/tmp/fakefish',
  engine_name: 'FakeFish',
  engine_version: '1.2',
  syzygy_available: false,
  syzygy_path: '/tmp/missing',
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
  time_presets_ms: [500, 800, 2000, 4000, 8000],
  multipv_max: 5,
  install_hint: null,
};

function engineAnalysis(fen: string) {
  const blackToMove = fen === e4Fen;
  return {
    id: blackToMove ? 'analysis-e4' : 'analysis-root',
    fen,
    source: 'engine',
    engine_name: 'FakeFish',
    engine_version: '1.2',
    parameters: engineCapabilities.default_parameters,
    lines: blackToMove
      ? [
          {
            rank: 1,
            score_cp: 20,
            mate: null,
            wdl: [400, 400, 200],
            uci: ['e7e5', 'g1f3'],
            san: ['e5', 'Nf3'],
          },
        ]
      : [
          {
            rank: 1,
            score_cp: 34,
            mate: null,
            wdl: [420, 400, 180],
            uci: ['e2e4', 'e7e5', 'g1f3'],
            san: ['e4', 'e5', 'Nf3'],
          },
          {
            rank: 2,
            score_cp: 27,
            mate: null,
            wdl: null,
            uci: ['d2d4', 'd7d5'],
            san: ['d4', 'd5'],
          },
          {
            rank: 3,
            score_cp: 18,
            mate: null,
            wdl: null,
            uci: ['g1f3', 'd7d5'],
            san: ['Nf3', 'd5'],
          },
          {
            rank: 4,
            score_cp: 12,
            mate: null,
            wdl: null,
            uci: ['c2c4', 'e7e5'],
            san: ['c4', 'e5'],
          },
        ],
    depth: 12,
    seldepth: 16,
    nodes: 1004,
    elapsed_ms: 800,
    from_cache: false,
    created_at: '2026-08-10T00:00:00Z',
  };
}

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

function renderEditor() {
  return render(
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      <MemoryRouter initialEntries={['/learn/course-1']}>
        <Routes>
          <Route path="/learn/:courseId" element={<CourseEditor />} />
        </Routes>
      </MemoryRouter>
    </SWRConfig>,
  );
}

describe('Stage 4B course editor', () => {
  it('auto-analyzes every selected course position and draws configurable MultiPV arrows', async () => {
    const analyzedFens: string[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/citable-sources') return json([]);
      if (url === '/api/courses/course-1') return json(course);
      if (url === '/api/courses/course-1/modules') return json([module]);
      if (url === '/api/courses/course-1/editor/module-1') {
        return json({
          module,
          content_blocks: [],
          occurrences: [root, e4],
          notes: [],
        });
      }
      if (url === '/api/engine/capabilities') return json(engineCapabilities);
      if (url === '/api/engine/analyses' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { fen: string };
        analyzedFens.push(body.fen);
        return json(engineAnalysis(body.fen));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderEditor();

    fireEvent.click(
      await screen.findByRole('switch', { name: '课程实时引擎分析' }),
    );
    expect(await screen.findByText('e4 e5 Nf3')).toBeTruthy();
    await waitFor(() => expect(analyzedFens).toContain(startFen));
    const arrows = screen.getByTestId('board-arrows');
    await waitFor(() => {
      expect(arrows.textContent).toContain('e2');
      expect(arrows.textContent).toContain('e4');
      expect(arrows.textContent).toContain('d2');
      expect(arrows.textContent).toContain('g1');
      expect(arrows.textContent).not.toContain('c2');
    });

    fireEvent.click(screen.getByRole('button', { name: '课程引擎设置' }));
    expect(await screen.findByText('分析线路：4')).toBeTruthy();
    expect(screen.getByText('推荐箭头：3')).toBeTruthy();
    fireEvent.mouseDown(
      screen.getByRole('combobox', { name: '课程引擎搜索时间' }),
    );
    fireEvent.click(await screen.findByText('2 秒'));
    fireEvent.click(screen.getByRole('switch', { name: '显示引擎推荐箭头' }));
    await waitFor(() => expect(arrows.textContent).toBe('[]'));
    fireEvent.click(screen.getByRole('switch', { name: '显示引擎推荐箭头' }));
    fireEvent.click(screen.getByLabelText('Close'));

    fireEvent.click(screen.getByRole('button', { name: /e4 e2e4/ }));
    expect(await screen.findByText('e5 Nf3')).toBeTruthy();
    await waitFor(() => expect(analyzedFens).toContain(e4Fen));
    await waitFor(() => {
      expect(arrows.textContent).toContain('e7');
      expect(arrows.textContent).toContain('e5');
      expect(arrows.textContent).not.toContain('e2');
    });
  });

  it('loads mixed content, follows candidates, exposes transpositions, and appends a legal move', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/citable-sources') return json([citableSource]);
      if (init?.method === 'POST' && url === '/api/occurrences') {
        return json(
          { ...e4, id: 'occ-nf3', inbound_uci: 'g1f3', inbound_san: 'Nf3' },
          201,
        );
      }
      if (url === '/api/courses/course-1') return json(course);
      if (url === '/api/courses/course-1/modules') return json([module]);
      if (url === '/api/courses/course-1/editor/module-1') {
        return json({
          module,
          content_blocks: [
            {
              id: 'block-1',
              module_id: 'module-1',
              kind: 'narrative',
              sort_order: 0,
              heading: null,
              markdown: '**安全的说明**',
              source_span_ids: ['span-1'],
              occurrence_id: null,
              knowledge_note_id: null,
              version: 1,
              archived_at: null,
            },
            {
              id: 'block-2',
              module_id: 'module-1',
              kind: 'move_sequence',
              sort_order: 1,
              heading: null,
              markdown: null,
              source_span_ids: [],
              root_occurrence_id: 'occ-root',
              knowledge_note_id: null,
              version: 1,
              archived_at: null,
            },
            {
              id: 'block-3',
              module_id: 'module-1',
              kind: 'knowledge_note',
              sort_order: 2,
              heading: null,
              markdown: null,
              source_span_ids: [],
              root_occurrence_id: null,
              knowledge_note_id: 'note-1',
              version: 1,
              archived_at: null,
            },
          ],
          occurrences: [root, e4, transposedRoot],
          notes: [{ ...note, rendered_source_span_ids: [] }],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderEditor();

    expect(
      await screen.findByRole('heading', { name: '可交互课程' }),
    ).toBeTruthy();
    expect(await screen.findByText('安全的说明')).toBeTruthy();
    expect(screen.getByText('Source One')).toBeTruthy();
    expect(screen.getByText('Initial explanation')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '查看关联局面' }));
    fireEvent.click(screen.getByRole('button', { name: /交互棋谱从这里开始/ }));
    expect(await screen.findByText('转置 × 2')).toBeTruthy();
    const boardFeedback = screen.getByTestId('board-feedback');
    expect(boardFeedback.getAttribute('data-animation-duration')).toBe('100');
    fireEvent.click(screen.getByRole('button', { name: '选择 e2' }));
    await waitFor(() => {
      expect(boardFeedback.textContent).toContain('"e3"');
      expect(boardFeedback.textContent).toContain('"e4"');
      expect(boardFeedback.textContent).not.toContain('"e5"');
    });
    fireEvent.click(screen.getByRole('button', { name: '选择 e2' }));
    fireEvent.click(screen.getByRole('button', { name: /e4 e2e4/ }));
    expect((await screen.findAllByText(e4Fen)).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: /^起\s*点$/ }));
    fireEvent.click(screen.getByRole('button', { name: '走 e4' }));
    expect((await screen.findAllByText(e4Fen)).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: /^起\s*点$/ }));
    fireEvent.click(screen.getByRole('button', { name: '走 Nf3' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/occurrences',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            kind: 'move',
            parent_occurrence_id: 'occ-root',
            uci: 'g1f3',
            sort_order: 1,
          }),
        }),
      ),
    );
  });

  it('shows a persistent clickable mainline score and removes keyboard move entry', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/citable-sources') return json([]);
      if (url === '/api/courses/course-1') return json(course);
      if (url === '/api/courses/course-1/modules') return json([module]);
      if (url === '/api/courses/course-1/editor/module-1') {
        return json({
          module,
          content_blocks: [],
          occurrences: [root, e4, e5, nf3],
          notes: [],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderEditor();

    await screen.findByRole('navigation', { name: '主线棋谱' });
    expect(screen.queryByLabelText('键盘输入着法 UCI')).toBeNull();
    expect(screen.queryByRole('button', { name: '提交着法' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /e4 e2e4/ }));
    fireEvent.click(await screen.findByRole('button', { name: /e5 e7e5/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Nf3 g1f3/ }));

    const score = screen.getByRole('navigation', { name: '主线棋谱' });
    expect(within(score).getByText('1.')).toBeTruthy();
    expect(within(score).getByText('2.')).toBeTruthy();
    expect(within(score).getByRole('button', { name: 'e4' })).toBeTruthy();
    expect(within(score).getByRole('button', { name: 'e5' })).toBeTruthy();
    expect(within(score).getByRole('button', { name: 'Nf3' })).toBeTruthy();

    fireEvent.click(within(score).getByRole('button', { name: '起点' }));
    expect(screen.getByLabelText('测试棋盘').textContent).toContain(startFen);
    expect(within(score).getByRole('button', { name: 'Nf3' })).toBeTruthy();

    fireEvent.click(within(score).getByRole('button', { name: 'e5' }));
    expect(screen.getByLabelText('测试棋盘').textContent).toContain(
      e5.full_fen,
    );
  });

  it('adds source-ready narrative prose to the ordered reading flow', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/citable-sources') return json([citableSource]);
      if (url === '/api/courses/course-1') return json(course);
      if (url === '/api/courses/course-1/modules') return json([module]);
      if (url === '/api/courses/course-1/editor/module-1') {
        return json({
          module,
          content_blocks: [],
          occurrences: [root],
          notes: [],
        });
      }
      if (url === '/api/course-content-blocks' && init?.method === 'POST') {
        return json({ id: 'narrative-created' }, 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderEditor();

    fireEvent.click(await screen.findByRole('button', { name: /编\s*辑/ }));
    fireEvent.click(screen.getByRole('button', { name: /阅\s*读/ }));
    fireEvent.click(screen.getByRole('button', { name: /编\s*辑/ }));
    fireEvent.click(
      screen.getByRole('button', { name: '添加叙述正文', hidden: false }),
    );
    fireEvent.change(await screen.findByLabelText('叙述正文 Markdown'), {
      target: { value: 'A readable **book paragraph**.' },
    });
    fireEvent.click(screen.getByRole('button', { name: '添加到本章' }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/course-content-blocks',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            module_id: 'module-1',
            kind: 'narrative',
            sort_order: 0,
            markdown: 'A readable **book paragraph**.',
            source_span_ids: [],
          }),
        }),
      ),
    );
  });

  it('rejects illegal board moves locally and reports persistence failures', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/citable-sources') return json([]);
      if (init?.method === 'POST') return json({ message: '版本冲突' }, 409);
      if (url === '/api/courses/course-1') return json(course);
      if (url === '/api/courses/course-1/modules') return json([module]);
      return json({ module, content_blocks: [], occurrences: [root] });
    });
    vi.stubGlobal('fetch', fetchMock);
    renderEditor();
    await screen.findByRole('button', { name: '走非法棋步' });

    fireEvent.click(screen.getByRole('button', { name: '走非法棋步' }));
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST'),
    ).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: '走 Nf3' }));
    expect(await screen.findByText('版本冲突')).toBeTruthy();
  });

  it('creates a chapter with the standard initial position', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/citable-sources') return json([]);
      if (init?.method === 'POST') return json(module, 201);
      if (url === '/api/courses/course-1') return json(course);
      if (url === '/api/courses/course-1/modules') return json([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderEditor();
    await screen.findByRole('heading', { name: '可交互课程' });
    fireEvent.click(screen.getByRole('button', { name: '新建章节' }));
    fireEvent.change(await screen.findByLabelText('章节名称'), {
      target: { value: '新章节' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/course-modules',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            title: '新章节',
            start_fen: startFen,
            course_id: 'course-1',
            sort_order: 0,
          }),
        }),
      ),
    );
  });

  it('presents an explorer as one merged graph instead of source chapters', async () => {
    const explorerCourse = {
      ...course,
      id: 'course-1',
      title: '合并探索器',
      mode: 'opening_explorer',
    };
    const secondModule = {
      ...module,
      id: 'module-2',
      title: '来源章节 B',
      sort_order: 1,
    };
    const secondRoot = {
      ...root,
      id: 'occ-root-2',
      module_id: 'module-2',
    };
    const d4 = {
      ...e4,
      id: 'occ-d4',
      module_id: 'module-2',
      parent_id: 'occ-root-2',
      position_id: 'position-d4',
      inbound_uci: 'd2d4',
      inbound_san: 'd4',
    };
    const sourceNamedModule = { ...module, title: '来源章节 A' };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/citable-sources') return json([]);
      if (url === '/api/courses/course-1') return json(explorerCourse);
      if (url === '/api/courses/course-1/modules') {
        return json([sourceNamedModule, secondModule]);
      }
      if (url === '/api/courses/course-1/editor/module-1') {
        return json({
          module: sourceNamedModule,
          content_blocks: [],
          occurrences: [root, e4],
          notes: [],
        });
      }
      if (url === '/api/courses/course-1/editor/module-2') {
        return json({
          module: secondModule,
          content_blocks: [],
          occurrences: [secondRoot, d4],
          notes: [],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderEditor();

    expect(await screen.findByText('合并探索图')).toBeTruthy();
    expect(screen.queryByText('来源章节 A')).toBeNull();
    expect(screen.queryByText('来源章节 B')).toBeNull();
    expect(screen.queryByRole('button', { name: '入口局面 1' })).toBeNull();
    expect(screen.queryByRole('button', { name: '入口局面 2' })).toBeNull();
    expect(
      screen.getByText('当前只有一个连通入口，不再按来源章节拆分。'),
    ).toBeTruthy();
    expect(await screen.findByRole('button', { name: /e4 e2e4/ })).toBeTruthy();
    expect(await screen.findByRole('button', { name: /d4 d2d4/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '导入 PGN' })).toBeNull();
    expect(screen.getByRole('button', { name: '添加入口局面' })).toBeTruthy();
  });

  it('renders course and editor load errors explicitly', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json({}, 404)),
    );
    renderEditor();
    expect(await screen.findByText('课程不存在或无法读取')).toBeTruthy();
  });

  it('keeps failed Markdown edits recoverable, supports undo/redo, and opens history', async () => {
    let patchAttempts = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/citable-sources') return json([citableSource]);
      if (url === '/api/courses/course-1') return json(course);
      if (url === '/api/courses/course-1/modules') return json([module]);
      if (url === '/api/courses/course-1/editor/module-1') {
        return json({
          module,
          content_blocks: [],
          occurrences: [root],
          notes: [note],
        });
      }
      if (url === '/api/history/knowledge_note/note-1') {
        return json({
          entity_type: 'knowledge_note',
          entity_id: 'note-1',
          current_version: 2,
          revisions: [
            {
              id: 'revision-1',
              created_at: '2026-08-09T00:00:00Z',
              entity_type: 'knowledge_note',
              entity_id: 'note-1',
              entity_version: 1,
              snapshot: { markdown: 'Initial explanation' },
            },
          ],
        });
      }
      if (url === '/api/knowledge-notes/note-1' && init?.method === 'PATCH') {
        patchAttempts += 1;
        return patchAttempts === 1
          ? json({ message: 'temporary outage' }, 500)
          : json({ ...note, version: 2, markdown: 'Safe revised text' });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const view = renderEditor();
    fireEvent.click(await screen.findByRole('button', { name: /编\s*辑/ }));
    const textarea = (await screen.findByLabelText(
      'Markdown 说明',
    )) as HTMLTextAreaElement;
    expect(textarea.value).toBe('Initial explanation');

    fireEvent.change(textarea, {
      target: { value: '<script>alert(1)</script>Safe revised text' },
    });
    expect(screen.getByText('有未保存修改')).toBeTruthy();
    expect(view.container.querySelector('script')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /^撤\s*销$/ }));
    expect(textarea.value).toBe('Initial explanation');
    fireEvent.click(screen.getByRole('button', { name: /^重\s*做$/ }));
    expect(textarea.value).toContain('Safe revised text');

    fireEvent.click(screen.getByRole('button', { name: /保存说明/ }));
    expect(await screen.findByText('说明尚未保存')).toBeTruthy();
    expect(screen.getByText('temporary outage')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /^重\s*试$/ }));
    await waitFor(() => expect(patchAttempts).toBe(2));
    const patchCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url) === '/api/knowledge-notes/note-1' &&
        init?.method === 'PATCH',
    );
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({
      expected_version: 1,
      markdown: '<script>alert(1)</script>Safe revised text',
      source_span_ids: ['span-1'],
    });

    fireEvent.click(screen.getByRole('button', { name: /^历\s*史$/ }));
    expect(await screen.findByText('版本 1')).toBeTruthy();
    expect(screen.getByText('Initial explanation')).toBeTruthy();
  });

  it('creates a new note, renders live reference cards, and publishes the module', async () => {
    const reference = {
      ...note,
      id: 'reference-1',
      source_note_id: 'source-note-1',
      markdown: null,
      source_span_ids: [],
      rendered_markdown: 'Published **source opinion**',
      source_course_id: 'source-course',
      source_module_id: 'source-module',
      source_occurrence_id: 'source-occurrence',
    };
    const explorer = {
      ...course,
      id: 'explorer-1',
      title: 'Explorer Target',
      mode: 'opening_explorer',
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/citable-sources') return json([]);
      if (url === '/api/courses/course-1') return json(course);
      if (url === '/api/courses/course-1/modules') return json([module]);
      if (url === '/api/courses/course-1/editor/module-1') {
        return json({
          module,
          content_blocks: [],
          occurrences: [root],
          notes: [reference],
        });
      }
      if (url === '/api/courses/source-course/editor/source-module') {
        return json({
          module: { ...module, id: 'source-module', title: '原书章节' },
          content_blocks: [
            {
              id: 'source-prose',
              module_id: 'source-module',
              kind: 'narrative',
              sort_order: 0,
              heading: null,
              markdown: 'This is the **surrounding passage**.',
              root_occurrence_id: null,
              knowledge_note_id: null,
              source_span_ids: [],
              version: 1,
              archived_at: null,
            },
            {
              id: 'source-note-block',
              module_id: 'source-module',
              kind: 'knowledge_note',
              sort_order: 1,
              heading: null,
              markdown: null,
              root_occurrence_id: null,
              knowledge_note_id: 'source-note-1',
              source_span_ids: [],
              version: 1,
              archived_at: null,
            },
          ],
          occurrences: [],
          notes: [],
        });
      }
      if (url.startsWith('/api/courses?mode=opening_explorer'))
        return json([explorer]);
      if (
        url === '/api/course-modules/module-1/knowledge-note-blocks' &&
        init?.method === 'POST'
      )
        return json({ note, block: {} }, 201);
      if (
        url === '/api/courses/explorer-1/publish-modules' &&
        init?.method === 'POST'
      ) {
        return json({ publications: [] });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderEditor();
    fireEvent.click(await screen.findByRole('button', { name: /编\s*辑/ }));
    const textarea = (await screen.findByLabelText(
      'Markdown 说明',
    )) as HTMLTextAreaElement;
    expect(await screen.findByText('source opinion')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: '跳转到原始条目' }).getAttribute('href'),
    ).toBe(
      '/learn/source-course?module=source-module&occurrence=source-occurrence',
    );
    fireEvent.click(screen.getByRole('button', { name: '查看原文上下文' }));
    expect(await screen.findByText('surrounding passage')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Close'));
    fireEvent.change(textarea, { target: { value: 'My own explanation' } });
    fireEvent.click(screen.getByRole('button', { name: /保存说明/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/course-modules/module-1/knowledge-note-blocks',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            occurrence_id: 'occ-root',
            markdown: 'My own explanation',
            source_span_ids: [],
            review_status: 'approved',
          }),
        }),
      ),
    );

    fireEvent.click(screen.getByRole('button', { name: '发布到开局探索器' }));
    const target = await screen.findByLabelText('目标开局探索器');
    fireEvent.mouseDown(target);
    fireEvent.click(await screen.findByText('Explorer Target'));
    fireEvent.click(screen.getByRole('button', { name: /^发\s*布$/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/courses/explorer-1/publish-modules',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ module_ids: ['module-1'] }),
        }),
      ),
    );
  });

  it('imports PGN with one retry key and exposes chapter and current-line downloads', async () => {
    let importAttempts = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/citable-sources') return json([]);
      if (url === '/api/courses/course-1') return json(course);
      if (url === '/api/courses/course-1/modules') return json([module]);
      if (url === '/api/courses/course-1/editor/module-1') {
        return json({
          module,
          content_blocks: [],
          occurrences: [root],
          notes: [],
        });
      }
      if (url === '/api/pgn/imports' && init?.method === 'POST') {
        importAttempts += 1;
        return importAttempts === 1
          ? json({ message: 'import temporarily unavailable' }, 500)
          : json({ replayed: false, import_receipt: {} }, 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderEditor();
    await screen.findByRole('heading', { name: '可交互课程' });
    expect(
      (await screen.findByRole('link', { name: '导出章节 PGN' })).getAttribute(
        'href',
      ),
    ).toBe('/api/courses/course-1/pgn?module_id=module-1');
    expect(
      (await screen.findByRole('link', { name: '导出当前线' })).getAttribute(
        'href',
      ),
    ).toBe(
      '/api/courses/course-1/pgn?module_id=module-1&leaf_occurrence_id=occ-root',
    );

    fireEvent.click(screen.getByRole('button', { name: '导入 PGN' }));
    fireEvent.change(await screen.findByLabelText('PGN 来源标题'), {
      target: { value: 'Imported study' },
    });
    fireEvent.change(screen.getByLabelText('PGN 文本'), {
      target: { value: '[Event "Study"]\n\n1. e4 *' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^导\s*入$/ }));
    expect(
      await screen.findByText('import temporarily unavailable'),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /^导\s*入$/ }));
    await waitFor(() => expect(importAttempts).toBe(2));
    const importCalls = fetchMock.mock.calls.filter(
      ([url, init]) =>
        String(url) === '/api/pgn/imports' && init?.method === 'POST',
    );
    expect(importCalls[0]?.[1]?.headers).toEqual(importCalls[1]?.[1]?.headers);
    expect(JSON.parse(String(importCalls[1]?.[1]?.body))).toEqual({
      pgn: '[Event "Study"]\n\n1. e4 *',
      destination: {
        kind: 'existing_course',
        course_id: 'course-1',
        expected_version: 1,
      },
      source_title: 'Imported study',
    });
  });
});
