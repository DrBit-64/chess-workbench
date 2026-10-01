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
import type { PdfReviewDocument, PdfSourceEvidence } from '../logic/api/types';
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
    onPieceDrop?: (source: string, target: string) => boolean;
  }) => (
    <div
      data-testid={`board-${props.id ?? 'default'}`}
      data-position={props.position ?? ''}
      data-draggable={String(props.arePiecesDraggable ?? true)}
    >
      棋盘
      <button
        type="button"
        aria-label="模拟落子 c7c6"
        onClick={() => props.onPieceDrop?.('c7', 'c6')}
      />
      <button
        type="button"
        aria-label="模拟落子 c7c5"
        onClick={() => props.onPieceDrop?.('c7', 'c5')}
      />
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

function reviewSession(version = 1) {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    target_kind: 'extraction_run' as const,
    target_id: RUN_ID,
    baseline_normalized_ccef_sha256: 'a'.repeat(64),
    status: 'open' as const,
    version,
    revisions: Array.from({ length: version }, (_, index) => ({
      id: `${index + 1}`.padStart(8, '0') + '-3333-4333-8333-333333333333',
      parent_revision_id:
        index === 0
          ? null
          : `${index}`.padStart(8, '0') + '-3333-4333-8333-333333333333',
      revision_number: index + 1,
      package_sha256: 'a'.repeat(64),
      created_at: '2026-08-24T12:00:00Z',
    })),
    events: Array.from({ length: version }, (_, index) => ({
      id: `${index + 1}`.padStart(8, '0') + '-4444-4444-8444-444444444444',
      revision_id:
        `${index + 1}`.padStart(8, '0') + '-3333-4333-8333-333333333333',
      parent_version: index,
      resulting_version: index + 1,
      kind: index === 0 ? ('created' as const) : ('edited' as const),
      decisions: {},
      created_at: '2026-08-24T12:00:00Z',
    })),
    created_at: '2026-08-24T12:00:00Z',
    updated_at: '2026-08-24T12:00:00Z',
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

  it('jumps to move evidence on right click without permanent move-page badges', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument())),
    );
    renderPage();

    expect(
      (await screen.findByAltText('物理页 5 图片')).getAttribute('src'),
    ).toBe(pageUrl(5));

    const sequence = screen.getByText('王翼进攻').closest('section')!;
    expect(
      within(sequence).queryByRole('button', { name: '第 6 页' }),
    ).toBeNull();
    fireEvent.contextMenu(
      within(sequence).getByRole('button', { name: 'e5' }),
      {
        clientX: 300,
        clientY: 200,
      },
    );
    expect(screen.getByAltText('物理页 6 图片').getAttribute('src')).toBe(
      pageUrl(6),
    );
    expect(
      screen.getByRole('menuitem', { name: '来源：第 6 页' }),
    ).toBeTruthy();

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
    expect(screen.queryByText('非法')).toBeNull();
    expect(screen.queryByText('歧义')).toBeNull();

    const invalidNode = screen
      .getByText('Nf3')
      .closest('[data-validation-status]')!;
    expect(invalidNode.getAttribute('aria-disabled')).toBe('true');
    expect(invalidNode.getAttribute('data-validation-status')).toBe('invalid');
    expect(invalidNode.className).toContain('bg-red-100');
    const ambiguousNode = screen
      .getByText('d4')
      .closest('[data-validation-status]')!;
    expect(ambiguousNode.getAttribute('data-validation-status')).toBe(
      'ambiguous',
    );
    expect(ambiguousNode.className).toContain('bg-amber-100');
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

  it('renders compact mainline rows and explicit branch lines without status or page badges', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument())),
    );
    renderPage();

    const sequence = (await screen.findByText('王翼进攻')).closest('section')!;

    // Visual order of the move cells across the projected rows.
    const labels = ['e4', 'd4', 'e5', 'c5', 'Nf3'];
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

    // The root white alternative separates e4 from e5; both remain mainline.
    const pairRow = within(sequence)
      .getByText('e5')
      .closest('[data-variation-depth]') as HTMLElement;
    expect(pairRow.getAttribute('data-variation-depth')).toBe('0');
    expect(within(pairRow).queryByText('e4')).toBeNull();
    expect(within(pairRow).getByText('1...')).toBeTruthy();

    // A line branching directly from the main score keeps an explicit rail.
    const c5Row = within(sequence)
      .getByText('c5')
      .closest('[data-variation-depth]') as HTMLElement;
    expect(c5Row.getAttribute('data-variation-depth')).toBe('1');
    expect(c5Row.getAttribute('data-variation-path')).toBe('n3');
    expect(c5Row.getAttribute('data-variation-presentation')).toBe('rail');
    expect(c5Row.querySelectorAll('[data-branch-rail]')).toHaveLength(1);
    expect(within(c5Row).getByText('1...')).toBeTruthy();

    // Nf3 is a mainline fallback; d4 is a separate alternative root.
    const nf3Row = within(sequence)
      .getByText('Nf3')
      .closest('[data-variation-depth]') as HTMLElement;
    expect(nf3Row.getAttribute('data-variation-depth')).toBe('0');
    const d4Row = within(sequence)
      .getByText('d4')
      .closest('[data-variation-depth]') as HTMLElement;
    expect(d4Row.getAttribute('data-variation-depth')).toBe('1');
    expect(d4Row.getAttribute('data-variation-path')).toBe('n5');
    expect(d4Row.getAttribute('data-variation-presentation')).toBe('rail');

    expect(within(sequence).queryByText('合法')).toBeNull();
    expect(within(sequence).queryByText('非法')).toBeNull();
    expect(within(sequence).queryByText('歧义')).toBeNull();
    expect(within(sequence).getAllByText('!').length).toBeGreaterThan(0);
    expect(within(sequence).getByText('?')).toBeTruthy();
    expect(
      within(sequence).queryByRole('button', { name: '第 5 页' }),
    ).toBeNull();
    expect(
      within(sequence).queryByRole('button', { name: '第 6 页' }),
    ).toBeNull();
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

  it('offers the explicit edit entry without mutating during read-only browsing', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return json(baseDocument());
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    await screen.findByText('第1章 引言');

    expect(screen.getByRole('button', { name: '开始编辑审核' })).toBeTruthy();
    for (const forbidden of ['批准', '拒绝', '发布', '保存', '删除']) {
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
      {
        input: `/api/pdf-extractions/${RUN_ID}/source`,
        method: undefined,
      },
    ]);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it('opens a review session and sends the Lichess-style promote command', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const target = String(input);
      if (target.endsWith('/review/session')) {
        return json({ replayed: false, session: reviewSession() }, 201);
      }
      if (target.endsWith('/commands')) {
        return json({ session: reviewSession(2), document: baseDocument() });
      }
      void init;
      return json(baseDocument());
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    expect(await screen.findByText('审核中 · 版本 1')).toBeTruthy();

    fireEvent.contextMenu(screen.getByRole('button', { name: 'c5' }), {
      clientX: 300,
      clientY: 200,
    });
    const promote = screen.getByRole('menuitem', { name: '提升变招' });
    expect((promote as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(promote);

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith('/commands'),
        ),
      ).toBe(true),
    );
    const commandCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/commands'),
    )!;
    expect(JSON.parse(String(commandCall[1]?.body))).toEqual({
      expected_version: 1,
      command: {
        kind: 'edit',
        operation: {
          kind: 'promote_variation',
          sequence_id: 'seq1',
          node_id: 'n3',
        },
      },
    });
    expect(await screen.findByText('审核中 · 版本 2')).toBeTruthy();
  });

  it('previews recovered moves without writing, confirms one revision, and can undo it', async () => {
    const original = baseDocument();
    const recoveredNode: MoveNode = {
      id: 'recovered-nc3',
      parent_id: 'n2',
      sibling_order: 1,
      move_text: 'Nc3',
      san_candidate: 'Nc3',
      uci_candidate: 'b1c3',
      fen_before: FEN_AFTER_E5,
      fen_after:
        'rnbqkbnr/pppp1ppp/8/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR b KQkq - 1 2',
      side_to_move: 'w',
      move_number: 2,
      nags: [],
      validation_status: 'valid',
      evidence: evidence(6),
      confidence: 0.8,
    };
    const candidate = {
      ...original.package,
      items: (original.package.items ?? []).map((item) =>
        item.kind === 'move_sequence' && item.id === 'seq1'
          ? { ...item, nodes: [...item.nodes, recoveredNode] }
          : item,
      ),
    };
    const commands: unknown[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const target = String(input);
      if (target.endsWith('/review/session')) {
        return json({ replayed: false, session: reviewSession() }, 201);
      }
      if (target.endsWith('/recovery-preview')) {
        expect(JSON.parse(String(init?.body))).toEqual({ expected_version: 1 });
        return json({
          preview_sha256: 'f'.repeat(64),
          corrected_entries: ['Nf3 → e5'],
          added_moves: [
            {
              page: 6,
              move_text: 'Nc3',
              sequence_id: 'seq1',
              node_id: 'recovered-nc3',
            },
          ],
          retired_issue_count: 1,
          preserved_manual_moves: 2,
          conflicts: [],
          candidate,
          inspection: {
            ...original.inspection,
            move_node_count: original.inspection.move_node_count + 1,
          },
        });
      }
      if (target.endsWith('/commands')) {
        commands.push(JSON.parse(String(init?.body)));
        return json({
          session: reviewSession(commands.length + 1),
          document:
            commands.length === 1
              ? { ...original, package: candidate }
              : original,
        });
      }
      return json(original);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    await screen.findByText('审核中 · 版本 1');
    fireEvent.click(
      screen.getByRole('button', { name: '根据人工修正恢复后续' }),
    );
    expect(await screen.findByText(/依赖恢复预览 · 新增 1 招/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Nc3' })).toBeTruthy();
    expect(commands).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: '对照原审核结果' }));
    expect(screen.queryByRole('button', { name: 'Nc3' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '查看恢复候选' }));
    fireEvent.click(screen.getByRole('button', { name: '确认恢复' }));
    await waitFor(() => expect(commands).toHaveLength(1));
    expect(commands[0]).toEqual({
      expected_version: 1,
      command: { kind: 'recover_dependencies', preview_sha256: 'f'.repeat(64) },
    });
    expect(await screen.findByText('审核中 · 版本 2')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(commands).toHaveLength(2));
    expect(commands[1]).toEqual({
      expected_version: 2,
      command: { kind: 'undo' },
    });
  });

  it('drags a whole branch to a visible move and offers undo and redo', async () => {
    const commands: unknown[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const target = String(input);
      if (target.endsWith('/review/session')) {
        return json({ replayed: false, session: reviewSession() }, 201);
      }
      if (target.endsWith('/reattach-preview')) {
        return json({ issue_count: 2, blocking_issue_count: 1 });
      }
      if (target.endsWith('/commands')) {
        commands.push(JSON.parse(String(init?.body)));
        const nextVersion = commands.length + 1;
        const session = reviewSession(nextVersion);
        if (nextVersion >= 3)
          session.events[2].decisions = { operation: 'undo' };
        if (nextVersion >= 4)
          session.events[3].decisions = { operation: 'redo' };
        return json({ session, document: baseDocument() });
      }
      return json(baseDocument());
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    await screen.findByText('审核中 · 版本 1');

    const transferred = new Map<string, string>();
    const dataTransfer = {
      types: [] as string[],
      effectAllowed: 'move',
      dropEffect: 'move',
      setData(type: string, value: string) {
        transferred.set(type, value);
        this.types = [...transferred.keys()];
      },
      getData(type: string) {
        return transferred.get(type) ?? '';
      },
    };
    const source = screen.getByText('Nf3').closest('[data-review-node-id]')!;
    const target = screen.getByRole('button', { name: 'c5' });
    fireEvent.dragStart(source, { dataTransfer });
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });
    expect(await screen.findByText('预览整段变化的挂接')).toBeTruthy();
    expect(screen.getByText(/来源：.*Nf3/)).toBeTruthy();
    await screen.findByText(/按新局面计算：剩余 2 个问题/);
    fireEvent.click(screen.getByRole('button', { name: '保存改挂' }));
    await waitFor(() => expect(commands).toHaveLength(1));
    expect(commands[0]).toEqual({
      expected_version: 1,
      command: {
        kind: 'edit',
        operation: {
          kind: 'reattach_variation',
          sequence_id: 'seq1',
          node_id: 'n4',
          target_sequence_id: 'seq1',
          parent_node_id: 'n3',
        },
      },
    });
    fireEvent.click(await screen.findByRole('button', { name: '撤销' }));
    await waitFor(() => expect(commands).toHaveLength(2));
    expect(commands[1]).toEqual({
      expected_version: 2,
      command: { kind: 'undo' },
    });
    fireEvent.click(await screen.findByRole('button', { name: '恢复' }));
    await waitFor(() => expect(commands).toHaveLength(3));
    expect(commands[2]).toEqual({
      expected_version: 3,
      command: { kind: 'redo' },
    });
  });

  it('can explicitly exclude a blocking non-score item from the audit revision', async () => {
    const figure = {
      id: 'photo1',
      kind: 'figure',
      figure_type: 'photo',
      caption: 'Player portrait',
      alt_text: null,
      evidence: evidence(6),
      confidence: null,
      position_fen_candidate: null,
      warnings: [],
    } satisfies ReviewItem;
    const blocked = baseDocument({
      items: [...baseItems(), figure],
      issues: [
        {
          issue_id: 'item:photo1:unsupported-figure',
          item_id: 'photo1',
          node_id: null,
          scope: 'item',
          severity: 'error',
          code: 'unsupported_figure',
          message: 'Non-chess figures require explicit rejection',
          blocking: true,
          evidence: evidence(6),
        },
      ],
      issueCounts: { issue_count: 1, blocking_issue_count: 1 },
    });
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const target = String(input);
      if (target.endsWith('/review/session')) {
        return json({ replayed: false, session: reviewSession() }, 201);
      }
      if (target.endsWith('/commands')) {
        return json({
          session: reviewSession(2),
          document: baseDocument({
            issues: [],
            issueCounts: { issue_count: 0, blocking_issue_count: 0 },
          }),
        });
      }
      void init;
      return json(blocked);
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage();

    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    fireEvent.click(await screen.findByRole('button', { name: '排除此内容' }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith('/commands'),
        ),
      ).toBe(true),
    );
    const commandCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/commands'),
    )!;
    expect(JSON.parse(String(commandCall[1]?.body))).toEqual({
      expected_version: 1,
      command: {
        kind: 'edit',
        operation: { kind: 'exclude_item', item_id: 'photo1' },
      },
    });
  });

  it('keeps annotation text while detaching an unmatched position anchor', async () => {
    const blocked = annotatedDocument();
    const sequence = blocked.package.items?.[0];
    if (
      sequence === undefined ||
      sequence.kind !== 'move_sequence' ||
      !('annotations' in sequence) ||
      sequence.annotations === undefined
    ) {
      throw new Error('Expected an annotated score fixture');
    }
    sequence.annotations[0] = {
      ...sequence.annotations[0]!,
      anchor: { kind: 'position', fen: CUSTOM_INITIAL_FEN },
    };
    blocked.inspection = {
      ...blocked.inspection,
      issue_count: 1,
      blocking_issue_count: 1,
      issues: [
        {
          issue_id: 'annotation:annotated-seq:a1:position-anchor-no-match',
          item_id: 'annotated-seq',
          node_id: null,
          scope: 'annotation',
          severity: 'error',
          code: 'position_anchor_no_match',
          message: 'Position anchor has no candidate occurrence',
          blocking: true,
          evidence: evidence(6),
        },
      ],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const target = String(input);
      if (target.endsWith('/review/session')) {
        return json({ replayed: false, session: reviewSession() }, 201);
      }
      if (target.endsWith('/commands')) {
        return json({
          session: reviewSession(2),
          document: annotatedDocument(),
        });
      }
      return json(blocked);
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage();

    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    fireEvent.click(
      await screen.findByRole('button', {
        name: '保留文字并取消局面关联',
      }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith('/commands'),
        ),
      ).toBe(true),
    );
    const commandCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/commands'),
    )!;
    expect(JSON.parse(String(commandCall[1]?.body))).toEqual({
      expected_version: 1,
      command: {
        kind: 'edit',
        operation: {
          kind: 'detach_position_anchor',
          issue_id: 'annotation:annotated-seq:a1:position-anchor-no-match',
        },
      },
    });
    expect(screen.getByText('第一条原子说明')).toBeTruthy();
  });

  it('drag-selects moves and publishes one fragment into a new nested chapter', async () => {
    const courseId = '55555555-5555-4555-8555-555555555555';
    const publicationItems = baseItems().map((item): ReviewItem =>
      item.kind === 'move_sequence'
        ? {
            ...item,
            nodes: item.nodes.map((node) =>
              node.id === 'n5'
                ? {
                    ...node,
                    move_text: 'e4',
                    san_candidate: 'e4',
                    uci_candidate: 'e2e4',
                    fen_before: START_FEN,
                    fen_after: FEN_AFTER_E4,
                    side_to_move: 'w',
                    move_number: 1,
                    validation_status: 'valid',
                  }
                : node,
            ),
          }
        : item,
    );
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const target = String(input);
      if (target.endsWith('/review/session')) {
        return json({
          replayed: true,
          session: { ...reviewSession(), status: 'approved' },
        });
      }
      if (target.startsWith('/api/courses?')) {
        return json([
          {
            id: courseId,
            title: 'Smerdon Scandinavian',
            description: '',
            category: null,
            tags: [],
            status: 'draft',
            mode: 'traditional',
            version: 1,
            created_at: '2026-08-28T00:00:00Z',
            updated_at: '2026-08-28T00:00:00Z',
            archived_at: null,
          },
        ]);
      }
      if (target === `/api/courses/${courseId}/modules`) return json([]);
      if (target.endsWith('/publications') && init?.method === 'POST') {
        return json(
          {
            publication_id: '66666666-6666-4666-8666-666666666666',
            review_session_id: reviewSession().id,
            review_revision_number: 1,
            target_course_id: courseId,
            mapping_version: 'review-course-publication/1.0',
            plan_sha256: 'f'.repeat(64),
            segments: [],
            replayed: false,
          },
          201,
        );
      }
      return json(baseDocument({ items: publicationItems }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const { container } = renderPage();

    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    fireEvent.click(await screen.findByRole('button', { name: '编排发布' }));
    await screen.findByRole('option', { name: 'Smerdon Scandinavian' });
    const mainlineRoot = container.querySelector('[data-review-node-id="n1"]')!;
    const alternateRoot = container.querySelector(
      '[data-review-node-id="n5"]',
    )!;
    const e5 = screen.getByRole('button', { name: 'e5' });
    const c5 = screen.getByRole('button', { name: 'c5' });
    const score = container.querySelector(
      'section[aria-label="候选内容与自动检查"]',
    )!;
    function placeAt(element: Element, top: number) {
      vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
        top,
        bottom: top + 20,
        left: 0,
        right: 100,
        width: 100,
        height: 20,
        x: 0,
        y: top,
        toJSON: () => ({}),
      });
    }
    placeAt(mainlineRoot, 0);
    placeAt(alternateRoot, 40);
    placeAt(e5, 100);
    placeAt(c5, 140);
    fireEvent.mouseDown(mainlineRoot, { clientY: 10 });
    fireEvent.mouseMove(score, { clientY: 110 });
    fireEvent.mouseUp(window);
    // Moving through blank space beside the moves still selects the full row range.
    expect(screen.getByText(/当前已选 4 个半回合/)).toBeTruthy();
    expect(alternateRoot.getAttribute('data-publication-selected')).toBe(
      'true',
    );
    expect(
      screen
        .getByRole('button', { name: 'c5' })
        .getAttribute('data-publication-selected'),
    ).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: '清空当前选择' }));
    fireEvent.mouseDown(screen.getByRole('button', { name: 'e5' }));
    fireEvent.mouseUp(window);
    fireEvent.mouseDown(alternateRoot);
    fireEvent.mouseUp(window);
    expect(screen.getByText(/当前已选 4 个半回合/)).toBeTruthy();
    expect(alternateRoot.getAttribute('data-publication-selected')).toBe(
      'true',
    );
    expect(
      screen
        .getByRole('button', { name: 'e5' })
        .getAttribute('data-publication-selected'),
    ).toBe('true');
    expect(
      screen
        .getByRole('button', { name: 'c5' })
        .getAttribute('data-publication-selected'),
    ).toBe('true');
    fireEvent.change(screen.getByLabelText('新章节标题'), {
      target: { value: 'Chapter Eight' },
    });
    fireEvent.change(screen.getByLabelText('目标小节'), {
      target: { value: '__new__' },
    });
    fireEvent.change(screen.getByLabelText('新小节标题'), {
      target: { value: 'Game 1' },
    });
    fireEvent.click(screen.getByRole('button', { name: '加入当前选择' }));
    fireEvent.click(screen.getByRole('button', { name: '原子发布全部片段' }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith('/publications'),
        ),
      ).toBe(true),
    );
    const publishCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/publications'),
    )!;
    expect(JSON.parse(String(publishCall[1]?.body))).toEqual({
      expected_version: 1,
      target_course_id: courseId,
      mapping_version: 'review-course-publication/1.1',
      segments: [
        {
          sequence_id: 'seq1',
          node_ids: ['n1', 'n2', 'n3', 'n5'],
          target: {
            chapter: { kind: 'new', title: 'Chapter Eight' },
            subsection: { kind: 'new', title: 'Game 1' },
          },
        },
      ],
    });
    expect(
      await screen.findByRole('link', { name: '打开已发布书籍' }),
    ).toBeTruthy();
  });

  it('moves annotation source and editing into its right-click menu', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith('/review/session')) {
        return json({ replayed: false, session: reviewSession() }, 201);
      }
      return json(annotatedDocument());
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    await screen.findByText('审核中 · 版本 1');

    const annotation = screen
      .getByText('变化结论')
      .closest('[data-annotation-id]') as HTMLElement;
    expect(
      within(annotation).queryByRole('button', { name: '第 6 页' }),
    ).toBeNull();
    fireEvent.contextMenu(annotation, { clientX: 360, clientY: 240 });

    expect(screen.getByAltText('物理页 6 图片')).toBeTruthy();
    expect(
      screen.getByRole('menuitem', { name: '来源：第 6 页' }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('menuitem', { name: '编辑注释' }));
    const dialog = await screen.findByRole('dialog');
    expect(
      (within(dialog).getByRole('textbox') as HTMLTextAreaElement).value,
    ).toBe('**变化结论**');
  });

  it('turns a source fragment into a branch by clicking its parent and entering printed notation', async () => {
    const document = annotatedDocument();
    document.package.items?.push({
      id: 'miss1',
      kind: 'unresolved',
      unresolved_type: 'mixed',
      reason_code: 'ambiguous_relation',
      raw_text: '1...c5?',
      details: null,
      evidence: evidence(5),
      confidence: null,
    });
    const fetchMock = vi.fn((...args: [RequestInfo | URL, RequestInit?]) => {
      const [input] = args;
      if (String(input).endsWith('/review/session')) {
        return json({ replayed: false, session: reviewSession() }, 201);
      }
      if (String(input).endsWith('/commands')) {
        return json({ session: reviewSession(2), document });
      }
      return json(document);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    await screen.findByText('审核中 · 版本 1');
    fireEvent.click(screen.getByRole('button', { name: '转为棋步' }));
    expect(screen.getByText(/请在棋谱中点选目标棋步/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'e4' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryByText(/UCI/)).toBeNull();
    expect(within(dialog).getByText('预览线路：c5?')).toBeTruthy();
    expect(within(dialog).getByText('接在 1. e4! 后面')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: '保存修订' }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith('/commands'),
        ),
      ).toBe(true),
    );
    const commandCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/commands'),
    )!;
    expect(JSON.parse(String(commandCall[1]?.body))).toEqual({
      expected_version: 1,
      command: {
        kind: 'edit',
        operation: {
          kind: 'resolve_unresolved',
          item_id: 'miss1',
          as_kind: 'line',
          text: null,
          sequence_id: 'annotated-seq',
          anchor_node_id: 'n1',
          moves: ['c7c5'],
          nags: [2],
          initial_fen: null,
        },
      },
    });
  });

  it('accepts a board move when the source notation cannot be read', async () => {
    const document = annotatedDocument();
    document.package.items?.push({
      id: 'miss1',
      kind: 'unresolved',
      unresolved_type: 'mixed',
      reason_code: 'ambiguous_relation',
      raw_text: 'unreadable',
      details: null,
      evidence: evidence(5),
      confidence: null,
    });
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        String(input).endsWith('/review/session')
          ? json({ replayed: false, session: reviewSession() }, 201)
          : json(document),
      ),
    );
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    await screen.findByText('审核中 · 版本 1');
    fireEvent.click(screen.getByRole('button', { name: '转为棋步' }));
    fireEvent.click(screen.getByRole('button', { name: 'e4' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/无法从此局面走出/)).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole('button', { name: '模拟落子 c7c5' }),
    );
    expect(within(dialog).getByText('预览线路：c5')).toBeTruthy();
    expect(
      (
        within(dialog).getByRole('textbox', {
          name: /棋步/,
        }) as HTMLTextAreaElement
      ).value,
    ).toBe('c5');
  });

  it('previews and saves a later unresolved continuation in the same revision', async () => {
    const document = annotatedDocument();
    document.package.items?.push(
      {
        id: 'miss1',
        kind: 'unresolved',
        unresolved_type: 'mixed',
        reason_code: 'ambiguous_relation',
        raw_text: '1...c5?',
        details: null,
        evidence: evidence(5),
        confidence: null,
      },
      {
        id: 'miss2',
        kind: 'unresolved',
        unresolved_type: 'mixed',
        reason_code: 'semantic_chunk_failed',
        raw_text: '2.Nf3',
        details: null,
        evidence: evidence(6),
        confidence: null,
      },
    );
    const fetchMock = vi.fn((...args: [RequestInfo | URL, RequestInit?]) => {
      const [input] = args;
      if (String(input).endsWith('/review/session')) {
        return json({ replayed: false, session: reviewSession() }, 201);
      }
      if (String(input).endsWith('/commands')) {
        return json({ session: reviewSession(2), document });
      }
      return json(document);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    await screen.findByText('审核中 · 版本 1');
    fireEvent.click(screen.getAllByRole('button', { name: '转为棋步' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'e4' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('第 6 页：Nf3')).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole('checkbox', {
        name: '同时恢复后续 1 段连续棋步',
      }),
    );
    fireEvent.click(within(dialog).getByRole('button', { name: '保存修订' }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith('/commands'),
        ),
      ).toBe(true),
    );
    const commandCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/commands'),
    )!;
    expect(
      JSON.parse(String(commandCall[1]?.body)).command.operation,
    ).toMatchObject({
      kind: 'resolve_unresolved',
      item_id: 'miss1',
      moves: ['c7c5'],
      nags: [2],
      following: [{ item_id: 'miss2', moves: ['g1f3'] }],
    });
  });

  it('offers a parallel branch at the selected move and keeps text when the position is wrong', async () => {
    const document = annotatedDocument();
    document.package.items?.push({
      id: 'miss1',
      kind: 'unresolved',
      unresolved_type: 'mixed',
      reason_code: 'ambiguous_relation',
      raw_text: '1...c5?',
      details: null,
      evidence: evidence(5),
      confidence: null,
    });
    const fetchMock = vi.fn((...args: [RequestInfo | URL, RequestInit?]) =>
      String(args[0]).endsWith('/review/session')
        ? json({ replayed: false, session: reviewSession() }, 201)
        : json(document),
    );
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    await screen.findByText('审核中 · 版本 1');
    fireEvent.click(screen.getByRole('button', { name: '转为棋步' }));
    fireEvent.click(screen.getByRole('button', { name: 'e5' }));
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByText(/来源步号 1\.\.\. 与所选局面不符/),
    ).toBeTruthy();
    expect(
      (
        within(dialog).getByRole('button', {
          name: '保存修订',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: '替代这步' }));
    expect(within(dialog).getByText('预览线路：c5?')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: '保存修订' }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith('/commands'),
        ),
      ).toBe(true),
    );
    const commandCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/commands'),
    )!;
    expect(
      JSON.parse(String(commandCall[1]?.body)).command.operation,
    ).toMatchObject({
      sequence_id: 'annotated-seq',
      anchor_node_id: 'n1',
      moves: ['c7c5'],
    });
  });

  it('records a board move as a new variation from the selected position', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const target = String(input);
      if (target.endsWith('/review/session')) {
        return json({ replayed: false, session: reviewSession() }, 201);
      }
      if (target.endsWith('/commands')) {
        return json({ session: reviewSession(2), document: baseDocument() });
      }
      void init;
      return json(baseDocument());
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    await screen.findByText('审核中 · 版本 1');
    fireEvent.click(screen.getByRole('button', { name: 'e4' }));
    fireEvent.click(screen.getByRole('button', { name: '模拟落子 c7c6' }));
    expect(await screen.findByText(/待保存线路：c6/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '保存线路' }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith('/commands'),
        ),
      ).toBe(true),
    );
    const commandCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/commands'),
    )!;
    expect(JSON.parse(String(commandCall[1]?.body))).toEqual({
      expected_version: 1,
      command: {
        kind: 'edit',
        operation: {
          kind: 'add_line',
          sequence_id: 'seq1',
          parent_node_id: 'n1',
          moves: ['c7c6'],
          evidence_page: 5,
        },
      },
    });
  });

  it('renders a linear white/black pair on one dense row with source in its context menu', async () => {
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
    expect(within(row).getByText('1')).toBeTruthy();

    expect(within(row).queryByText('合法')).toBeNull();
    expect(within(row).queryByRole('button', { name: '第 5 页' })).toBeNull();
    fireEvent.contextMenu(e4, { clientX: 320, clientY: 220 });
    expect(
      screen.getByRole('menuitem', { name: '来源：第 5 页' }),
    ).toBeTruthy();

    // Board navigation and compact symbolic NAGs are preserved.
    fireEvent.click(e4);
    expect(
      screen
        .getByTestId('board-pdf-review-board')
        .getAttribute('data-position'),
    ).toBe(FEN_AFTER_E4);
    expect(within(row).getAllByText('!')).toHaveLength(2);
    expect(within(row).getByText('?')).toBeTruthy();
  });

  it('shows canonical SAN and one styled annotation in the review score', async () => {
    const items = pairItems();
    const sequence = items[0] as MoveSequenceItem;
    sequence.nodes[0] = {
      ...sequence.nodes[0],
      move_text: 'e4!',
      nags: [],
      extensions: { 'chess-workbench.nag-override': true },
    };
    sequence.nodes[1] = {
      ...sequence.nodes[1],
      move_text: 'e5?!',
      san_candidate: 'e5',
      nags: [],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json(baseDocument({ items }))),
    );
    renderPage();

    const move = await screen.findByRole('button', { name: 'e5' });
    const cleared = screen.getByRole('button', { name: 'e4' });
    expect(within(cleared).queryByText('!')).toBeNull();
    expect(within(move).getByText('e5')).toBeTruthy();
    expect(within(move).getAllByText('?!')).toHaveLength(1);
    expect(within(move).getByTitle('可疑着法').className).toContain(
      'text-amber-700',
    );
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
    fireEvent.click(within(sequence).getByText('第一条原子说明'));
    expect(board.getAttribute('data-position')).toBe(FEN_AFTER_E4);
    fireEvent.click(within(sequence).getByText('变化结论'));
    expect(board.getAttribute('data-position')).toBe(FEN_AFTER_C5);

    expect(
      within(annotations[1] as HTMLElement).queryByRole('button', {
        name: '第 6 页',
      }),
    ).toBeNull();
    fireEvent.contextMenu(annotations[1] as HTMLElement, {
      clientX: 360,
      clientY: 240,
    });
    expect(screen.getByAltText('物理页 6 图片').getAttribute('src')).toBe(
      pageUrl(6),
    );
    expect(
      screen.getByRole('menuitem', { name: '来源：第 6 页' }),
    ).toBeTruthy();
  });

  it('links recorded prose moves, flags a separate occurrence and filters only commentary', async () => {
    const document = baseDocument();
    const sequence = document.package.items!.find(
      (item) => item.kind === 'move_sequence',
    )! as MoveSequenceItem;
    const rows = [
      {
        id: 'known',
        text: '1 e4 is active.',
        hash: 'a'.repeat(64),
        raw: 'e4',
        roles: [],
      },
      {
        id: 'missing',
        text: 'Again 1 e4 is considered.',
        hash: 'b'.repeat(64),
        raw: 'e4',
        roles: [],
      },
      {
        id: 'plan',
        text: 'The plan is h7-h6.',
        hash: 'c'.repeat(64),
        raw: 'h7-h6',
        roles: ['plan'] as const,
      },
    ];
    const precise = (
      row: (typeof rows)[number],
      start: number,
      end: number,
    ): EvidenceRef[] => [
      {
        page: 5,
        bbox: null,
        fragment_sha256: row.hash,
        start_offset: start,
        end_offset: end,
      },
    ];
    sequence.nodes = [baseNodes()[0]];
    sequence.nodes[0].evidence = precise(rows[0], 2, 4);
    document.package.items = [
      sequence,
      ...rows.map((row): ReviewItem => ({
        kind: 'prose',
        id: row.id,
        text: row.text,
        text_format: 'plain',
        anchor: null,
        confidence: null,
        evidence: precise(row, 0, row.text.length),
      })),
    ];
    const source: PdfSourceEvidence = {
      run_id: RUN_ID,
      first_page: 5,
      last_page: 6,
      evidence_status: 'ready',
      error_code: null,
      pages: [
        {
          physical_page: 5,
          fragments: rows.map((row) => ({
            order: rows.indexOf(row),
            text: row.text,
            origin: 'embedded_text',
            bbox: {},
            fragment_sha256: row.hash,
            roles: [...row.roles],
            move_mentions: [
              {
                start: row.text.indexOf(row.raw),
                end: row.text.indexOf(row.raw) + row.raw.length,
                kind: 'candidate',
              },
            ],
          })),
        },
      ],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        json(String(input).endsWith('/source') ? source : document),
      ),
    );
    renderPage();
    const link = await screen.findByRole('button', {
      name: 'e4，已入谱，定位棋步',
    });
    expect(screen.getAllByText('已入谱 1 招').length).toBeGreaterThan(0);
    expect(screen.getAllByText('计划 1（未入谱）').length).toBeGreaterThan(0);
    expect(
      screen.getByLabelText('e4，待核对：当前棋谱没有唯一对应节点'),
    ).toBeTruthy();
    fireEvent.click(link);
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: 'e4' })
          .getAttribute('data-source-linked'),
      ).toBe('true'),
    );
    expect(
      screen
        .getByTestId('board-pdf-review-board')
        .getAttribute('data-position'),
    ).toBe(FEN_AFTER_E4);
    fireEvent.click(
      screen.getByRole('checkbox', { name: '只看待核对段落（1）' }),
    );
    expect(
      window.document.querySelector('[data-source-item-id=known]'),
    ).toBeNull();
    expect(
      window.document.querySelector('[data-source-item-id=plan]'),
    ).toBeNull();
    expect(
      screen.getByLabelText('e4，待核对：当前棋谱没有唯一对应节点'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'e4' })).toBeTruthy();
  });

  it('groups source commentary and lets a prose score become a move', async () => {
    const document = annotatedDocument();
    for (const [index, text] of [
      '1...c5?',
      'A first explanation.',
      'A second explanation.',
    ].entries()) {
      document.package.items?.push({
        id: `source-${index}`,
        kind: 'prose',
        text_format: 'plain',
        text,
        anchor: null,
        evidence: evidence(5),
        confidence: null,
      });
    }
    const fetchMock = vi.fn((...args: [RequestInfo | URL, RequestInit?]) => {
      const [input] = args;
      if (String(input).endsWith('/review/session')) {
        return json({ replayed: false, session: reviewSession() }, 201);
      }
      if (String(input).endsWith('/commands')) {
        return json({ session: reviewSession(2), document });
      }
      return json(document);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: '开始编辑审核' }),
    );
    await screen.findByText('审核中 · 版本 1');
    fireEvent.click(screen.getByText(/第 5 页讲解 · 3 段/));
    fireEvent.click(screen.getAllByRole('button', { name: '转为棋步' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'e4' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('预览线路：c5?')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: '保存修订' }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).endsWith('/commands')),
      ).toBe(true),
    );
    const call = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith('/commands'),
    )!;
    expect(JSON.parse(String(call[1]?.body)).command.operation).toMatchObject({
      kind: 'resolve_unresolved',
      item_id: 'source-0',
      as_kind: 'line',
      anchor_node_id: 'n1',
      moves: ['c7c5'],
    });
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
    expect(root.className).toContain('lg:h-[calc(100vh-12rem)]');
    expect(root.className).toContain('lg:grid-cols-3');
    expect(root.className).toContain('lg:overflow-hidden');

    // The board lives outside both scroll panes.
    const board = screen.getByTestId('board-pdf-review-board');
    expect(source.contains(board)).toBe(false);
    expect(candidate.contains(board)).toBe(false);
  });
});
