import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { SWRConfig, mutate } from 'swr';
import { describe, expect, it, vi } from 'vitest';

import { PdfReviewPage } from './PdfReviewPage';
import type { PdfReviewDocument } from '../logic/api/types';
import type { AnnotatedMoveSequenceItem } from './reviewMoveLayout';

const RUN_ID = '11111111-1111-4111-8111-111111111111';
const RUN_ID_2 = '22222222-2222-4222-8222-222222222222';
const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
// Exact normalized fen(en_passant="fen") values used by the authoritative
// normalizer; side_to_move is the side about to move (pre-move side).
const FEN_AFTER_E4 =
  'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1';
const FEN_AFTER_E5 =
  'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2';
const FEN_AFTER_C5 =
  'rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2';
const CUSTOM_INITIAL_FEN = '8/8/8/4k3/8/8/8/4K3 w - - 0 1';
const CUSTOM_AFTER_KD2 = '8/8/8/4k3/8/8/3K4/8 b - - 1 1';
const ANCHOR_FEN = '8/8/8/4k3/8/8/8/4K3 w - - 0 1';

type ReviewItem = NonNullable<PdfReviewDocument['package']['items']>[number];
type MoveSequenceItem = Extract<ReviewItem, { kind: 'move_sequence' }>;
type MoveNode = MoveSequenceItem['nodes'][number];
type ReviewIssue = PdfReviewDocument['inspection']['issues'][number];
type EvidenceRef = ReviewItem['evidence'][number];
type ReviewPage = PdfReviewDocument['pages'][number];

const pageUrl = (page: number, runId: string = RUN_ID) =>
  `/api/pdf-extractions/${runId}/review/pages/${page}`;
const reviewUrl = (runId: string) =>
  `/api/pdf-extractions/${encodeURIComponent(runId)}/review`;

vi.mock('react-chessboard', () => ({
  Chessboard: (props: {
    id?: string;
    position?: string;
    arePiecesDraggable?: boolean;
  }) => (
    <div
      data-testid={`board-${props.id ?? 'default'}`}
      data-position={props.position ?? ''}
      data-draggable={String(props.arePiecesDraggable ?? true)}
    >
      棋盘
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

function renderPage(runId: string = RUN_ID) {
  return render(
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      <PdfReviewPage runId={runId} />
    </SWRConfig>,
  );
}

function evidence(page: number): EvidenceRef[] {
  return [
    {
      page,
      bbox: null,
      start_offset: null,
      end_offset: null,
      fragment_sha256: null,
    },
  ];
}

function baseNodes(): MoveNode[] {
  return [
    {
      id: 'n1',
      parent_id: null,
      sibling_order: 0,
      move_text: 'e4',
      san_candidate: 'e4',
      uci_candidate: 'e2e4',
      fen_before: START_FEN,
      fen_after: FEN_AFTER_E4,
      side_to_move: 'w',
      move_number: 1,
      nags: [1],
      validation_status: 'valid',
      evidence: evidence(5),
      confidence: 0.9,
    },
    {
      id: 'n2',
      parent_id: 'n1',
      sibling_order: 0,
      move_text: 'e5',
      san_candidate: 'e5',
      uci_candidate: 'e7e5',
      fen_before: FEN_AFTER_E4,
      fen_after: FEN_AFTER_E5,
      side_to_move: 'b',
      move_number: 1,
      nags: [1, 2],
      validation_status: 'valid',
      evidence: evidence(6),
      confidence: 0.9,
    },
    {
      id: 'n3',
      parent_id: 'n1',
      sibling_order: 1,
      move_text: 'c5',
      san_candidate: 'c5',
      uci_candidate: 'c7c5',
      fen_before: FEN_AFTER_E4,
      fen_after: FEN_AFTER_C5,
      side_to_move: 'b',
      move_number: 1,
      nags: [],
      validation_status: 'valid',
      evidence: evidence(5),
      confidence: 0.8,
    },
    {
      id: 'n4',
      parent_id: 'n2',
      sibling_order: 0,
      move_text: 'Nf3',
      san_candidate: null,
      uci_candidate: null,
      fen_before: null,
      fen_after: null,
      side_to_move: null,
      move_number: null,
      nags: [],
      validation_status: 'invalid',
      evidence: evidence(6),
      confidence: null,
    },
    {
      id: 'n5',
      parent_id: null,
      sibling_order: 1,
      move_text: 'd4',
      san_candidate: null,
      uci_candidate: null,
      fen_before: null,
      fen_after: null,
      side_to_move: null,
      move_number: null,
      nags: [],
      validation_status: 'ambiguous',
      evidence: evidence(5),
      confidence: null,
    },
  ];
}

// Frozen legal one-node custom-FEN sequence: kings only, White Kd2.
function customFenItems(): ReviewItem[] {
  return [
    {
      id: 'cseq1',
      kind: 'move_sequence',
      title: '王与王',
      initial_position: { kind: 'fen', fen: CUSTOM_INITIAL_FEN },
      nodes: [
        {
          id: 'cn1',
          parent_id: null,
          sibling_order: 0,
          move_text: 'Kd2',
          san_candidate: 'Kd2',
          uci_candidate: 'e1d2',
          fen_before: CUSTOM_INITIAL_FEN,
          fen_after: CUSTOM_AFTER_KD2,
          side_to_move: 'w',
          move_number: 1,
          nags: [],
          validation_status: 'valid',
          evidence: evidence(5),
          confidence: 0.9,
        },
      ],
      evidence: evidence(5),
      confidence: null,
    },
  ];
}

// A single startpos sequence with a same-page white/black pair (both page 5).
function pairItems(): ReviewItem[] {
  return [
    {
      id: 'pairseq1',
      kind: 'move_sequence',
      title: '双着示例',
      initial_position: { kind: 'startpos' },
      nodes: [
        {
          id: 'pe1',
          parent_id: null,
          sibling_order: 0,
          move_text: 'e4',
          san_candidate: 'e4',
          uci_candidate: 'e2e4',
          fen_before: START_FEN,
          fen_after: FEN_AFTER_E4,
          side_to_move: 'w',
          move_number: 1,
          nags: [1],
          validation_status: 'valid',
          evidence: evidence(5),
          confidence: 0.9,
        },
        {
          id: 'pe2',
          parent_id: 'pe1',
          sibling_order: 0,
          move_text: 'e5',
          san_candidate: 'e5',
          uci_candidate: 'e7e5',
          fen_before: FEN_AFTER_E4,
          fen_after: FEN_AFTER_E5,
          side_to_move: 'b',
          move_number: 1,
          nags: [1, 2],
          validation_status: 'valid',
          evidence: evidence(5),
          confidence: 0.9,
        },
      ],
      evidence: evidence(5),
      confidence: null,
    },
  ];
}

function annotatedDocument(): PdfReviewDocument {
  const nodes = baseNodes().slice(0, 3);
  const sequence: AnnotatedMoveSequenceItem = {
    id: 'annotated-seq',
    kind: 'move_sequence',
    title: '带谱内注释的棋谱',
    initial_position: { kind: 'startpos' },
    nodes,
    annotations: [
      {
        id: 'a1',
        text: '第一条原子说明',
        text_format: 'plain',
        anchor: { kind: 'move_node', node_id: 'n1', relation: 'after' },
        evidence: evidence(5),
        confidence: 0.9,
      },
      {
        id: 'a2',
        text: '**变化结论**',
        text_format: 'markdown',
        anchor: { kind: 'move_node', node_id: 'n3', relation: 'after' },
        evidence: evidence(6),
        confidence: 0.8,
      },
    ],
    reading_flow: [
      { kind: 'move', node_id: 'n1' },
      { kind: 'annotation', annotation_id: 'a1' },
      { kind: 'move', node_id: 'n2' },
      { kind: 'move', node_id: 'n3' },
      { kind: 'annotation', annotation_id: 'a2' },
    ],
    evidence: evidence(5),
    confidence: 0.9,
  };
  const legacy = baseDocument({
    items: [],
    issues: [],
    issueCounts: { issue_count: 0, blocking_issue_count: 0 },
  });
  return {
    ...legacy,
    package: {
      ...legacy.package,
      schema_version: 'chess-content-extraction/1.1',
      items: [sequence],
      provenance: {
        ...legacy.package.provenance,
        adapter_version: '1.1',
      },
    },
    inspection: {
      ...legacy.inspection,
      item_count: 1,
      move_node_count: nodes.length,
    },
  };
}

function baseItems(): ReviewItem[] {
  return [
    {
      id: 'h1',
      kind: 'heading',
      level: 2,
      text: '第1章 引言',
      evidence: evidence(5),
      confidence: null,
    },
    {
      id: 'p1',
      kind: 'prose',
      text_format: 'plain',
      text: '第一段\n说明文字',
      anchor: null,
      evidence: evidence(5),
      confidence: null,
    },
    {
      id: 'p2',
      kind: 'prose',
      text_format: 'markdown',
      text: '**要点**\n\n<script>window.__xss = 1</script>\n\n<b>原始HTML</b>',
      anchor: { kind: 'position', fen: ANCHOR_FEN },
      evidence: evidence(6),
      confidence: null,
    },
    {
      id: 'p3',
      kind: 'prose',
      text_format: 'plain',
      text: '参见续着',
      anchor: { kind: 'move_node', sequence_id: 'seq1', node_id: 'n2' },
      evidence: [],
      confidence: null,
    },
    {
      id: 'seq1',
      kind: 'move_sequence',
      title: '王翼进攻',
      initial_position: { kind: 'startpos' },
      nodes: baseNodes(),
      evidence: evidence(5),
      confidence: null,
    },
    {
      id: 'f1',
      kind: 'figure',
      figure_type: 'chessboard',
      caption: '局面图',
      alt_text: '中局局面',
      position_fen_candidate: FEN_AFTER_E5,
      evidence: evidence(6),
      confidence: null,
    },
    {
      id: 'u1',
      kind: 'unresolved',
      unresolved_type: 'mixed',
      reason_code: 'unsupported-format',
      raw_text: '无法识别的残局表内容',
      details: '包含表格与图示的混合区域',
      evidence: evidence(5),
      confidence: null,
    },
    {
      id: 'h2',
      kind: 'heading',
      level: 3,
      text: '第二个标题',
      evidence: evidence(99),
      confidence: null,
    },
  ];
}

function baseIssues(): ReviewIssue[] {
  return [
    {
      issue_id: 'i1',
      item_id: 'seq1',
      node_id: 'n4',
      scope: 'node',
      severity: 'error',
      code: 'invalid-move',
      message: '棋步非法',
      blocking: true,
      evidence: evidence(6),
    },
    {
      issue_id: 'i2',
      item_id: 'h1',
      node_id: null,
      scope: 'item',
      severity: 'warning',
      code: 'heading-too-long',
      message: '标题过长',
      blocking: false,
      evidence: evidence(5),
    },
  ];
}

function baseDocument(overrides?: {
  runId?: string;
  issues?: ReviewIssue[];
  issueCounts?: { issue_count: number; blocking_issue_count: number };
  items?: ReviewItem[];
  pages?: ReviewPage[];
}): PdfReviewDocument {
  const runId = overrides?.runId ?? RUN_ID;
  const items = overrides?.items ?? baseItems();
  const issues = overrides?.issues ?? baseIssues();
  const issueCounts = overrides?.issueCounts ?? {
    issue_count: 2,
    blocking_issue_count: 1,
  };
  const pages = overrides?.pages ?? [
    {
      physical_page: 5,
      media_type: 'image/png',
      byte_size: 100,
      content_sha256: 'b'.repeat(64),
      content_url: pageUrl(5, runId),
    },
    {
      physical_page: 6,
      media_type: 'image/png',
      byte_size: 200,
      content_sha256: 'c'.repeat(64),
      content_url: pageUrl(6, runId),
    },
  ];
  const moveNodeCount = items.reduce(
    (total, item) =>
      item.kind === 'move_sequence' ? total + item.nodes.length : total,
    0,
  );
  return {
    run_id: runId,
    normalized_ccef_sha256: 'a'.repeat(64),
    package: {
      schema_version: 'chess-content-extraction/1.0',
      package_id: runId,
      source: {
        source_ref: 'opaque-1',
        media_type: 'application/pdf',
        language: 'zh',
        page_range: { start_page: 5, end_page: 6 },
      },
      items,
      provenance: {
        created_at: '2026-08-11T10:00:00Z',
        adapter_name: 'test-adapter',
        adapter_version: '1',
        model: null,
        provider: null,
        request_sha256: null,
        response_sha256: null,
      },
    },
    inspection: {
      inspection_version: 'ccef-review-inspection/1.0',
      issue_count: issueCounts.issue_count,
      blocking_issue_count: issueCounts.blocking_issue_count,
      item_count: items.length,
      move_node_count: moveNodeCount,
      issues,
    },
    pages,
  };
}

describe('Stage 8D review page (8D-3A)', () => {
  it('fetches the exact review URL and shows an accessible busy state', async () => {
    let resolveFetch!: (value: Response) => void;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    expect(screen.getByRole('status')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      reviewUrl(RUN_ID),
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    );

    await act(async () => {
      resolveFetch(
        new Response(JSON.stringify(baseDocument()), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });
    expect(await screen.findByText('第1章 引言')).toBeTruthy();
  });

  it.each([
    [404, '审核资料不存在'],
    [409, '审核资料尚不可用'],
    [503, '来源页暂时不可用'],
    [500, '加载审核资料失败'],
  ])('shows the sanitized alert for status %i', async (status, expected) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        json({ message: 'secret internal detail /srv/path' }, status),
      ),
    );
    renderPage();

    const alert = await screen.findByText(expected);
    expect(alert).toBeTruthy();
    expect(screen.queryByText(/secret/)).toBeNull();
    expect(screen.queryByText(/srv\/path/)).toBeNull();
  });

  it('renders the first page with server-ordered controls and exact content_url', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument())),
    );
    renderPage();

    const image = await screen.findByAltText('物理页 5 图片');
    expect(image.getAttribute('src')).toBe(pageUrl(5));
    expect(screen.getByText('物理页 5')).toBeTruthy();

    const controls = within(screen.getByLabelText('页面切换')).getAllByRole(
      'button',
    );
    expect(controls.map((button) => button.textContent)).toEqual([
      '第 5 页',
      '第 6 页',
    ]);

    fireEvent.click(controls[1]);
    expect(screen.getByAltText('物理页 6 图片').getAttribute('src')).toBe(
      pageUrl(6),
    );
    expect(screen.getByText('物理页 6')).toBeTruthy();
  });

  it('selects pages from evidence and ignores out-of-document evidence pages', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument())),
    );
    renderPage();

    expect(
      (await screen.findByAltText('物理页 5 图片')).getAttribute('src'),
    ).toBe(pageUrl(5));

    const sequence = screen.getByText('王翼进攻').closest('section')!;
    fireEvent.click(
      within(sequence).getAllByRole('button', { name: '第 6 页' })[0],
    );
    expect(screen.getByAltText('物理页 6 图片').getAttribute('src')).toBe(
      pageUrl(6),
    );

    // Out-of-document evidence page 99 (heading h2): clicking changes nothing.
    fireEvent.click(screen.getAllByRole('button', { name: '第 99 页' })[0]);
    expect(screen.getByAltText('物理页 6 图片').getAttribute('src')).toBe(
      pageUrl(6),
    );
    expect(screen.queryByAltText(/物理页 99/)).toBeNull();
  });

  it('renders all item kinds in source order with safe markdown and complete unresolved text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument())),
    );
    renderPage();

    expect(
      await screen.findByRole('heading', { level: 2, name: /第1章 引言/ }),
    ).toBeTruthy();
    expect(
      screen.getByRole('heading', { level: 3, name: /第二个标题/ }),
    ).toBeTruthy();

    // Markdown rendered through the sanitizer: bold text present, raw HTML escaped.
    expect(screen.getByText('要点')).toBeTruthy();
    expect(document.querySelector('b')).toBeNull();
    expect(document.querySelector('script')).toBeNull();
    expect((window as unknown as { __xss?: number }).__xss).toBeUndefined();

    // Plain prose preserves whitespace.
    expect(screen.getByText(/说明文字/).className).toContain(
      'whitespace-pre-wrap',
    );

    // Complete unresolved content and reason code.
    expect(screen.getByText(/未解析内容（unsupported-format）/)).toBeTruthy();
    expect(screen.getByText('无法识别的残局表内容')).toBeTruthy();
    expect(screen.getByText('包含表格与图示的混合区域')).toBeTruthy();

    // Strict source order across all eight items, including both headings.
    const texts = [
      '第1章 引言',
      /第一段/,
      '要点',
      '参见续着',
      '王翼进攻',
      '图形（chessboard）',
      '无法识别的残局表内容',
      '第二个标题',
    ];
    const elements = texts.map((text) => screen.getByText(text));
    for (let index = 1; index < elements.length; index += 1) {
      const before = elements[index - 1];
      const after = elements[index];
      expect(
        (before.compareDocumentPosition(after) &
          Node.DOCUMENT_POSITION_FOLLOWING) !==
          0,
      ).toBe(true);
    }
  });

  it('starts on the first sequence start FEN and navigates via valid nodes and prose anchors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument())),
    );
    renderPage();

    const board = await screen.findByTestId('board-pdf-review-board');
    expect(board.getAttribute('data-position')).toBe(START_FEN);
    expect(board.getAttribute('data-draggable')).toBe('false');

    fireEvent.click(screen.getByRole('button', { name: 'e4' }));
    expect(board.getAttribute('data-position')).toBe(FEN_AFTER_E4);

    fireEvent.click(screen.getByRole('button', { name: 'c5' }));
    expect(board.getAttribute('data-position')).toBe(FEN_AFTER_C5);

    // 回到初始局面 resets to the sequence start.
    fireEvent.click(screen.getByRole('button', { name: '回到初始局面' }));
    expect(board.getAttribute('data-position')).toBe(START_FEN);

    // Prose position anchor sets its exact FEN.
    fireEvent.click(screen.getAllByRole('button', { name: '定位局面' })[0]);
    expect(board.getAttribute('data-position')).toBe(ANCHOR_FEN);

    // Prose move_node anchor locates the referenced valid node n2.
    fireEvent.click(screen.getAllByRole('button', { name: '定位局面' })[1]);
    expect(board.getAttribute('data-position')).toBe(FEN_AFTER_E5);
  });

  it('never changes the board for invalid or ambiguous nodes', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument())),
    );
    renderPage();

    const board = await screen.findByTestId('board-pdf-review-board');
    expect(board.getAttribute('data-position')).toBe(START_FEN);

    // Invalid and ambiguous nodes are visible but not navigable buttons.
    expect(screen.queryByRole('button', { name: 'Nf3' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'd4' })).toBeNull();
    expect(screen.getByText('非法')).toBeTruthy();
    expect(screen.getByText('歧义')).toBeTruthy();

    const invalidNode = screen.getByText('Nf3').closest('span')!;
    expect(invalidNode.getAttribute('aria-disabled')).toBe('true');
    expect(board.getAttribute('data-position')).toBe(START_FEN);
  });

  it('initializes the board from a declared initial FEN', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        json(
          baseDocument({
            items: customFenItems(),
            issues: [],
            issueCounts: { issue_count: 0, blocking_issue_count: 0 },
          }),
        ),
      ),
    );
    renderPage();

    const board = await screen.findByTestId('board-pdf-review-board');
    expect(board.getAttribute('data-position')).toBe(CUSTOM_INITIAL_FEN);

    // The frozen legal one-node sequence navigates to its exact fen_after.
    fireEvent.click(screen.getByRole('button', { name: 'Kd2' }));
    expect(board.getAttribute('data-position')).toBe(CUSTOM_AFTER_KD2);

    // Coherent inspection counts for the single-item, single-node package.
    expect(
      screen.getByText('问题 0 · 阻断 0 · 内容项 1 · 棋步 1'),
    ).toBeTruthy();
  });

  it('resets board and page when runId changes but keeps navigation on same-run revalidation', async () => {
    // Uses the default SWR cache so global mutate() can simulate revalidation.
    await mutate(() => true, undefined, { revalidate: false });
    const first = baseDocument();
    // Second run is internally coherent: the frozen custom-FEN sequence with
    // evidence page 5 sits inside the declared 5..6 page range, and the
    // rendered pages stay on 5/6 with RUN_ID_2 URLs.
    const second = baseDocument({
      runId: RUN_ID_2,
      items: customFenItems(),
      issues: [],
      issueCounts: { issue_count: 0, blocking_issue_count: 0 },
    });
    const fetchMock = vi.fn((input: RequestInfo | URL) =>
      String(input).includes(RUN_ID_2) ? json(second) : json(first),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { rerender } = render(<PdfReviewPage runId={RUN_ID} />);
    const board = await screen.findByTestId('board-pdf-review-board');
    expect(board.getAttribute('data-position')).toBe(START_FEN);
    expect(screen.getByAltText('物理页 5 图片')).toBeTruthy();

    // User navigation: node e4 and page 6.
    fireEvent.click(screen.getByRole('button', { name: 'e4' }));
    fireEvent.click(
      within(screen.getByLabelText('页面切换')).getAllByRole('button')[1],
    );
    expect(board.getAttribute('data-position')).toBe(FEN_AFTER_E4);
    expect(screen.getByAltText('物理页 6 图片')).toBeTruthy();

    // Same-run revalidation with a fresh document reference must not reset.
    await act(async () => {
      await mutate(reviewUrl(RUN_ID), { ...first }, { revalidate: false });
    });
    expect(board.getAttribute('data-position')).toBe(FEN_AFTER_E4);
    expect(screen.getByAltText('物理页 6 图片')).toBeTruthy();

    // A different runId on the same mounted instance resets board and page:
    // the board returns to the second run's custom initial FEN and the source
    // page resets from 6 back to the second run's page 5 URL (RUN_ID_2).
    rerender(<PdfReviewPage runId={RUN_ID_2} />);
    await waitFor(() =>
      expect(
        screen
          .getByTestId('board-pdf-review-board')
          .getAttribute('data-position'),
      ).toBe(CUSTOM_INITIAL_FEN),
    );
    expect(await screen.findByAltText('物理页 5 图片')).toBeTruthy();
    expect(screen.getByAltText('物理页 5 图片').getAttribute('src')).toBe(
      pageUrl(5, RUN_ID_2),
    );
  });

  it('renders branching move rows in source order with status, NAG and variation indentation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument())),
    );
    renderPage();

    const sequence = (await screen.findByText('王翼进攻')).closest('section')!;

    // Visual order of the move cells across the projected rows.
    const labels = ['e4', 'e5', 'c5', 'Nf3', 'd4'];
    const elements = labels.map((label) => within(sequence).getByText(label));
    for (let index = 1; index < elements.length; index += 1) {
      const before = elements[index - 1];
      const after = elements[index];
      expect(
        (before.compareDocumentPosition(after) &
          Node.DOCUMENT_POSITION_FOLLOWING) !==
          0,
      ).toBe(true);
    }

    // e4/e5 are one paired mainline row at variation depth 0.
    const pairRow = within(sequence)
      .getByText('e5')
      .closest('[data-variation-depth]') as HTMLElement;
    expect(pairRow.getAttribute('data-variation-depth')).toBe('0');
    expect(pairRow.style.paddingLeft).toBe('0px');
    expect(within(pairRow).getByText('e4')).toBeTruthy();
    expect(within(pairRow).getByText('1.')).toBeTruthy();

    // c5 is a black-only alternative row at depth 1 with a 1... gutter.
    const c5Row = within(sequence)
      .getByText('c5')
      .closest('[data-variation-depth]') as HTMLElement;
    expect(c5Row.getAttribute('data-variation-depth')).toBe('1');
    expect(c5Row.style.paddingLeft).toBe('16px');
    expect(within(c5Row).getByText('1...')).toBeTruthy();

    // Nf3 is a fallback row (depth 0); d4 a fallback row (depth 1).
    const nf3Row = within(sequence)
      .getByText('Nf3')
      .closest('[data-variation-depth]') as HTMLElement;
    expect(nf3Row.getAttribute('data-variation-depth')).toBe('0');
    expect(nf3Row.style.paddingLeft).toBe('0px');
    const d4Row = within(sequence)
      .getByText('d4')
      .closest('[data-variation-depth]') as HTMLElement;
    expect(d4Row.getAttribute('data-variation-depth')).toBe('1');
    expect(d4Row.style.paddingLeft).toBe('16px');

    expect(within(sequence).getAllByText('合法')).toHaveLength(3);
    expect(within(sequence).getByText('非法')).toBeTruthy();
    expect(within(sequence).getByText('歧义')).toBeTruthy();
    expect(within(sequence).getByText('NAG 1')).toBeTruthy();
    expect(within(sequence).getByText('NAG 1 2')).toBeTruthy();

    expect(
      within(sequence).getAllByRole('button', { name: '第 5 页' }).length,
    ).toBeGreaterThan(0);
    expect(
      within(sequence).getAllByRole('button', { name: '第 6 页' }).length,
    ).toBeGreaterThan(0);
  });

  it('renders backend issues in order with exact counts and scoped evidence navigation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument())),
    );
    renderPage();

    expect(
      await screen.findByText('问题 2 · 阻断 1 · 内容项 8 · 棋步 5'),
    ).toBeTruthy();
    expect(screen.getByText('阻断')).toBeTruthy();
    expect(screen.getByText('非阻断')).toBeTruthy();
    expect(screen.getByText('错误')).toBeTruthy();
    expect(screen.getByText('警告')).toBeTruthy();

    const messages = ['棋步非法', '标题过长'];
    const elements = messages.map((message) => screen.getByText(message));
    expect(
      (elements[0].compareDocumentPosition(elements[1]) &
        Node.DOCUMENT_POSITION_FOLLOWING) !==
        0,
    ).toBe(true);

    // Scoped oracle: click the issue row's own page-6 evidence button.
    expect(screen.getByAltText('物理页 5 图片')).toBeTruthy();
    const issueRow = screen.getByText('棋步非法').closest('li')!;
    fireEvent.click(within(issueRow).getByRole('button', { name: '第 6 页' }));
    expect(screen.getByAltText('物理页 6 图片').getAttribute('src')).toBe(
      pageUrl(6),
    );
  });

  it('shows the exact zero-issue empty state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        json(
          baseDocument({
            issues: [],
            issueCounts: { issue_count: 0, blocking_issue_count: 0 },
          }),
        ),
      ),
    );
    renderPage();

    expect(
      await screen.findByText('没有发现自动检查问题，但仍需人工批准'),
    ).toBeTruthy();
  });

  it('renders no edit/approve/publish controls and never mutates', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return json(baseDocument());
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    await screen.findByText('第1章 引言');

    for (const forbidden of ['批准', '拒绝', '发布', '编辑', '保存', '删除']) {
      expect(
        screen.queryByRole('button', { name: new RegExp(forbidden) }),
      ).toBeNull();
    }

    const calls = fetchMock.mock.calls.map(([input, init]) => ({
      input,
      method: (init as RequestInit | undefined)?.method,
    }));
    expect(calls).toEqual([
      {
        input: reviewUrl(RUN_ID),
        method: undefined,
      },
    ]);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });

  it('renders a linear white/black pair on one row with a single page control', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        json(
          baseDocument({
            items: pairItems(),
            issues: [],
            issueCounts: { issue_count: 0, blocking_issue_count: 0 },
          }),
        ),
      ),
    );
    renderPage();

    const sequence = (await screen.findByText('双着示例')).closest('section')!;
    const e4 = within(sequence).getByRole('button', { name: 'e4' });
    const e5 = within(sequence).getByText('e5');
    const row = e5.closest('[data-variation-depth]') as HTMLElement;
    expect(row.contains(e4)).toBe(true);
    expect(row.getAttribute('data-variation-depth')).toBe('0');
    expect(row.style.paddingLeft).toBe('0px');
    expect(within(row).getByText('1.')).toBeTruthy();

    // Same-page pair exposes exactly one row-level page control (no per-ply).
    expect(
      within(row).getAllByRole('button', { name: '第 5 页' }),
    ).toHaveLength(1);

    // Board navigation, status and NAG display are preserved on the pair row.
    fireEvent.click(e4);
    expect(
      screen
        .getByTestId('board-pdf-review-board')
        .getAttribute('data-position'),
    ).toBe(FEN_AFTER_E4);
    expect(within(row).getAllByText('合法')).toHaveLength(2);
    expect(within(row).getByText('NAG 1')).toBeTruthy();
    expect(within(row).getByText('NAG 1 2')).toBeTruthy();
  });

  it('renders CCEF 1.1 annotations in reading-flow order and navigates their anchors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(annotatedDocument())),
    );
    renderPage();

    const sequence = (await screen.findByText('带谱内注释的棋谱')).closest(
      'section',
    )!;
    const ordered = ['e4', '第一条原子说明', 'e5', 'c5', '变化结论'].map(
      (label) => within(sequence).getByText(label),
    );
    for (let index = 1; index < ordered.length; index += 1) {
      expect(
        (ordered[index - 1].compareDocumentPosition(ordered[index]) &
          Node.DOCUMENT_POSITION_FOLLOWING) !==
          0,
      ).toBe(true);
    }

    const c5Row = within(sequence)
      .getByText('c5')
      .closest('[data-variation-depth]') as HTMLElement;
    expect(c5Row.getAttribute('data-variation-depth')).toBe('1');
    const annotations = sequence.querySelectorAll('[data-annotation-id]');
    expect(
      [...annotations].map((entry) => entry.getAttribute('data-annotation-id')),
    ).toEqual(['a1', 'a2']);

    const board = screen.getByTestId('board-pdf-review-board');
    const anchorButtons = within(sequence).getAllByRole('button', {
      name: '定位注释局面',
    });
    fireEvent.click(anchorButtons[0]);
    expect(board.getAttribute('data-position')).toBe(FEN_AFTER_E4);
    fireEvent.click(anchorButtons[1]);
    expect(board.getAttribute('data-position')).toBe(FEN_AFTER_C5);

    fireEvent.click(
      within(annotations[1] as HTMLElement).getByRole('button', {
        name: '第 6 页',
      }),
    );
    expect(screen.getByAltText('物理页 6 图片').getAttribute('src')).toBe(
      pageUrl(6),
    );
  });

  it('scopes wide screens to independent scroll panes with accessible labels', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument())),
    );
    renderPage();

    const source = await screen.findByLabelText('原书页面');
    expect(source.className).toContain('lg:overflow-y-auto');
    expect(source.className).toContain('lg:overscroll-contain');
    expect(source.className).toContain('lg:h-full');

    const candidate = screen.getByLabelText('候选内容与自动检查');
    expect(candidate.getAttribute('tabindex')).toBe('0');
    expect(candidate.className).toContain('lg:overflow-y-auto');
    expect(candidate.className).toContain('lg:overscroll-contain');
    expect(candidate.className).toContain('lg:h-full');

    const root = source.parentElement!;
    expect(root.className).toContain('lg:h-[calc(100vh-9rem)]');
    expect(root.className).toContain('lg:grid-cols-3');
    expect(root.className).toContain('lg:overflow-hidden');

    // The board lives outside both scroll panes.
    const board = screen.getByTestId('board-pdf-review-board');
    expect(source.contains(board)).toBe(false);
    expect(candidate.contains(board)).toBe(false);
  });
});
