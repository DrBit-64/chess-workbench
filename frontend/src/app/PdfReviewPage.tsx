import { Alert, Spin, Tag } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Chessboard } from 'react-chessboard';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import useSWR from 'swr';

import { ApiError, fetchJson } from '../logic/api/client';
import type { PdfReviewDocument } from '../logic/api/types';
import { FAST_MOVE_ANIMATION_MS } from './boardInteraction';
import { buildReviewMoveRows } from './reviewMoveLayout';
import type { MoveNode, ReviewMoveRow } from './reviewMoveLayout';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

type ReviewItem = NonNullable<PdfReviewDocument['package']['items']>[number];
type MoveSequenceItem = Extract<ReviewItem, { kind: 'move_sequence' }>;
type ProseItem = Extract<ReviewItem, { kind: 'prose' }>;
type EvidenceRef = ReviewItem['evidence'][number];

const VALIDATION_LABELS: Record<MoveNode['validation_status'], string> = {
  valid: '合法',
  invalid: '非法',
  ambiguous: '歧义',
  unvalidated: '未验证',
};

const HEADING_TAGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] as const;

function reviewErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return '审核资料不存在';
    }
    if (error.status === 409) {
      return '审核资料尚不可用';
    }
    if (error.status === 503) {
      return '来源页暂时不可用';
    }
  }
  return '加载审核资料失败';
}

function sequenceStartFen(item: MoveSequenceItem): string {
  return item.initial_position.kind === 'fen'
    ? item.initial_position.fen
    : START_FEN;
}

function uniqueEvidencePages(evidence: EvidenceRef[]): number[] {
  return [...new Set(evidence.map((ref) => ref.page))];
}

export function PdfReviewPage({ runId }: { runId: string }) {
  const url = `/api/pdf-extractions/${encodeURIComponent(runId)}/review`;
  const { data, error, isLoading } = useSWR<PdfReviewDocument>(url, fetchJson);

  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [boardFen, setBoardFen] = useState<string>(START_FEN);
  const initializedRunId = useRef<string | null>(null);

  const pages = data?.pages ?? [];

  const items = useMemo(() => data?.package.items ?? [], [data]);

  const initialBoardFen = useMemo(() => {
    const firstSequence = items.find((item) => item.kind === 'move_sequence');
    return firstSequence && firstSequence.kind === 'move_sequence'
      ? sequenceStartFen(firstSequence)
      : START_FEN;
  }, [items]);

  useEffect(() => {
    if (data === undefined || initializedRunId.current === runId) {
      return;
    }
    // First verified document for this run identity: initialize both the
    // board and the source page. A same-run SWR revalidation keeps the
    // previous run's guard satisfied and must not reset user navigation.
    initializedRunId.current = runId;
    setBoardFen(initialBoardFen);
    setSelectedPage(data.pages[0]?.physical_page ?? null);
  }, [data, runId, initialBoardFen]);

  const activeDescriptor =
    pages.find((page) => page.physical_page === selectedPage) ?? pages[0];

  function selectPage(physicalPage: number) {
    if (pages.some((page) => page.physical_page === physicalPage)) {
      setSelectedPage(physicalPage);
    }
  }

  function selectNode(node: MoveNode) {
    if (node.validation_status === 'valid' && node.fen_after !== null) {
      setBoardFen(node.fen_after);
    }
  }

  function selectProseAnchor(item: ProseItem) {
    const anchor = item.anchor;
    if (anchor === null) {
      return;
    }
    if (anchor.kind === 'position') {
      setBoardFen(anchor.fen);
      return;
    }
    const sequence = items.find(
      (candidate) =>
        candidate.kind === 'move_sequence' &&
        candidate.id === anchor.sequence_id,
    );
    if (sequence === undefined || sequence.kind !== 'move_sequence') {
      return;
    }
    const node = sequence.nodes.find(
      (candidate) => candidate.id === anchor.node_id,
    );
    if (
      node !== undefined &&
      node.validation_status === 'valid' &&
      node.fen_after !== null
    ) {
      setBoardFen(node.fen_after);
    }
  }

  if (isLoading) {
    return (
      <div role="status" aria-busy="true" className="p-8 text-stone-600">
        <Spin description="正在加载审核资料" />
      </div>
    );
  }

  if (error !== undefined || data === undefined) {
    return (
      <Alert
        type="error"
        showIcon
        title={reviewErrorMessage(error)}
        role="alert"
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-6 p-6 lg:h-[calc(100vh-9rem)] lg:grid-cols-3 lg:overflow-hidden">
      <section
        aria-label="原书页面"
        className="min-w-0 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:overscroll-contain"
      >
        <div className="mb-3 flex flex-wrap gap-2" aria-label="页面切换">
          {pages.map((page) => (
            <button
              key={page.physical_page}
              type="button"
              onClick={() => setSelectedPage(page.physical_page)}
              className="rounded border border-stone-300 bg-white px-2 py-1 text-sm"
              aria-pressed={
                page.physical_page === (activeDescriptor?.physical_page ?? null)
              }
            >
              第 {page.physical_page} 页
            </button>
          ))}
        </div>
        {activeDescriptor !== undefined ? (
          <figure className="min-w-0">
            <img
              src={activeDescriptor.content_url}
              alt={`物理页 ${activeDescriptor.physical_page} 图片`}
              className="max-w-full"
            />
            <figcaption className="mt-1 text-sm text-stone-600">
              物理页 {activeDescriptor.physical_page}
            </figcaption>
          </figure>
        ) : null}
      </section>

      <section className="min-w-0">
        <div className="mx-auto max-w-[560px]">
          <Chessboard
            id="pdf-review-board"
            position={boardFen}
            animationDuration={FAST_MOVE_ANIMATION_MS}
            arePiecesDraggable={false}
            customBoardStyle={{
              borderRadius: '8px',
              boxShadow: '0 12px 30px rgba(28,25,23,.16)',
            }}
          />
        </div>
      </section>

      <section
        aria-label="候选内容与自动检查"
        tabIndex={0}
        className="min-w-0 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:overscroll-contain"
      >
        <div className="max-w-prose space-y-4">
          {items.map((item) => (
            <ReviewItemView
              key={item.id}
              item={item}
              onSelectPage={selectPage}
              onSelectNode={selectNode}
              onSelectAnchor={selectProseAnchor}
              onSelectSequenceStart={(sequence) =>
                setBoardFen(sequenceStartFen(sequence))
              }
            />
          ))}
        </div>
        <IssuesView document={data} onSelectPage={selectPage} />
      </section>
    </div>
  );
}

function ReviewItemView({
  item,
  onSelectPage,
  onSelectNode,
  onSelectAnchor,
  onSelectSequenceStart,
}: {
  item: ReviewItem;
  onSelectPage: (page: number) => void;
  onSelectNode: (node: MoveNode) => void;
  onSelectAnchor: (item: ProseItem) => void;
  onSelectSequenceStart: (item: MoveSequenceItem) => void;
}) {
  switch (item.kind) {
    case 'heading': {
      const tag = HEADING_TAGS[Math.min(5, Math.max(0, item.level - 1))];
      const Heading = tag;
      return (
        <Heading className="mt-4 mb-2 font-semibold text-stone-900">
          {item.text}
          <EvidencePages evidence={item.evidence} onSelectPage={onSelectPage} />
        </Heading>
      );
    }
    case 'prose': {
      return (
        <article>
          {item.text_format === 'markdown' ? (
            <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
              {item.text}
            </ReactMarkdown>
          ) : (
            <p className="whitespace-pre-wrap text-stone-800">{item.text}</p>
          )}
          <span className="mt-1 flex flex-wrap items-center gap-2">
            {item.anchor !== null ? (
              <button
                type="button"
                onClick={() => onSelectAnchor(item)}
                className="rounded border border-stone-300 bg-white px-2 py-0.5 text-xs"
              >
                定位局面
              </button>
            ) : null}
            <EvidencePages
              evidence={item.evidence}
              onSelectPage={onSelectPage}
            />
          </span>
        </article>
      );
    }
    case 'move_sequence': {
      return (
        <MoveSequenceView
          item={item}
          onSelectPage={onSelectPage}
          onSelectNode={onSelectNode}
          onSelectStart={onSelectSequenceStart}
        />
      );
    }
    case 'figure': {
      return (
        <figure className="rounded border border-amber-300 bg-amber-50 p-3">
          <figcaption className="font-semibold text-stone-800">
            图形（{item.figure_type}）
            <EvidencePages
              evidence={item.evidence}
              onSelectPage={onSelectPage}
            />
          </figcaption>
          {item.caption !== null ? (
            <p className="text-stone-700">说明：{item.caption}</p>
          ) : null}
          {item.alt_text !== null ? (
            <p className="text-stone-700">替代文本：{item.alt_text}</p>
          ) : null}
          {item.position_fen_candidate !== null ? (
            <p className="break-all font-mono text-xs text-stone-600">
              候选 FEN：{item.position_fen_candidate}
            </p>
          ) : null}
        </figure>
      );
    }
    case 'unresolved': {
      return (
        <div className="rounded border border-red-300 bg-red-50 p-3">
          <p className="font-semibold text-red-700">
            未解析内容（{item.reason_code}）
            <EvidencePages
              evidence={item.evidence}
              onSelectPage={onSelectPage}
            />
          </p>
          {item.raw_text !== null ? (
            <p className="whitespace-pre-wrap text-stone-800">
              {item.raw_text}
            </p>
          ) : null}
          {item.details !== null ? (
            <p className="whitespace-pre-wrap text-stone-700">{item.details}</p>
          ) : null}
        </div>
      );
    }
  }
}

function MoveSequenceView({
  item,
  onSelectPage,
  onSelectNode,
  onSelectStart,
}: {
  item: MoveSequenceItem;
  onSelectPage: (page: number) => void;
  onSelectNode: (node: MoveNode) => void;
  onSelectStart: (item: MoveSequenceItem) => void;
}) {
  const rows = useMemo(() => buildReviewMoveRows(item.nodes), [item.nodes]);
  return (
    <section className="rounded border border-stone-200 bg-white p-3">
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-stone-900">{item.title ?? '棋谱'}</h3>
        <button
          type="button"
          onClick={() => onSelectStart(item)}
          className="rounded border border-stone-300 bg-white px-2 py-0.5 text-xs"
        >
          回到初始局面
        </button>
        <EvidencePages evidence={item.evidence} onSelectPage={onSelectPage} />
      </header>
      <div className="space-y-1">
        {rows.map((row) => (
          <MoveRow
            key={row.key}
            row={row}
            onSelectPage={onSelectPage}
            onSelectNode={onSelectNode}
          />
        ))}
      </div>
    </section>
  );
}

function MoveRow({
  row,
  onSelectPage,
  onSelectNode,
}: {
  row: ReviewMoveRow;
  onSelectPage: (page: number) => void;
  onSelectNode: (node: MoveNode) => void;
}) {
  const visualDepth = Math.min(4, row.variationDepth);
  const gutter =
    row.fallback === null && row.moveNumber !== null
      ? row.white === null
        ? `${row.moveNumber}...`
        : `${row.moveNumber}.`
      : '';
  return (
    <div
      data-variation-depth={row.variationDepth}
      style={{ paddingLeft: `${visualDepth * 16}px` }}
      className={
        row.variationDepth > 0
          ? 'rounded border-l-2 border-amber-300 bg-amber-50/40 px-1 py-1'
          : 'py-1'
      }
    >
      <div className="grid grid-cols-[2.5rem_1fr_1fr] items-center gap-2">
        <span className="font-mono text-xs text-stone-500">{gutter}</span>
        {row.fallback !== null ? (
          <div className="col-span-2">
            <MoveCell node={row.fallback} onSelectNode={onSelectNode} />
          </div>
        ) : (
          <>
            <div className="min-w-0">
              {row.white !== null ? (
                <MoveCell node={row.white} onSelectNode={onSelectNode} />
              ) : null}
            </div>
            <div className="min-w-0">
              {row.black !== null ? (
                <MoveCell node={row.black} onSelectNode={onSelectNode} />
              ) : null}
            </div>
          </>
        )}
      </div>
      {row.evidencePages.length > 0 ? (
        <div className="mt-0.5">
          <EvidencePages
            evidence={rowEvidenceRefs(row.evidencePages)}
            onSelectPage={onSelectPage}
          />
        </div>
      ) : null}
    </div>
  );
}

function MoveCell({
  node,
  onSelectNode,
}: {
  node: MoveNode;
  onSelectNode: (node: MoveNode) => void;
}) {
  const isNavigable =
    node.validation_status === 'valid' && node.fen_after !== null;
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {isNavigable ? (
        <button
          type="button"
          onClick={() => onSelectNode(node)}
          className="rounded border border-stone-300 bg-white px-2 py-0.5 text-sm"
        >
          {node.move_text}
        </button>
      ) : (
        <span
          aria-disabled="true"
          className="rounded border border-stone-200 bg-stone-100 px-2 py-0.5 text-sm text-stone-400"
        >
          {node.move_text}
        </span>
      )}
      <Tag color={node.validation_status === 'valid' ? 'green' : 'default'}>
        {VALIDATION_LABELS[node.validation_status]}
      </Tag>
      {node.nags !== undefined && node.nags.length > 0 ? (
        <span className="font-mono text-xs text-stone-500">
          NAG {node.nags.join(' ')}
        </span>
      ) : null}
    </span>
  );
}

function rowEvidenceRefs(pages: number[]): EvidenceRef[] {
  return pages.map((page) => ({
    page,
    bbox: null,
    start_offset: null,
    end_offset: null,
    fragment_sha256: null,
  }));
}

function EvidencePages({
  evidence,
  onSelectPage,
}: {
  evidence: EvidenceRef[];
  onSelectPage: (page: number) => void;
}) {
  const pages = uniqueEvidencePages(evidence);
  if (pages.length === 0) {
    return null;
  }
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1">
      {pages.map((page) => (
        <button
          key={page}
          type="button"
          onClick={() => onSelectPage(page)}
          className="rounded bg-stone-200 px-1.5 py-0.5 text-xs"
        >
          第 {page} 页
        </button>
      ))}
    </span>
  );
}

function IssuesView({
  document,
  onSelectPage,
}: {
  document: PdfReviewDocument;
  onSelectPage: (page: number) => void;
}) {
  const { inspection } = document;
  return (
    <section className="mt-6">
      <h2 className="text-lg font-semibold text-stone-900">自动检查</h2>
      <p className="text-sm text-stone-600">
        问题 {inspection.issue_count} · 阻断 {inspection.blocking_issue_count} ·
        内容项 {inspection.item_count} · 棋步 {inspection.move_node_count}
      </p>
      {inspection.issues.length === 0 ? (
        <p className="rounded border border-emerald-300 bg-emerald-50 p-3 text-stone-800">
          没有发现自动检查问题，但仍需人工批准
        </p>
      ) : (
        <ol className="space-y-2">
          {inspection.issues.map((issue) => (
            <li
              key={issue.issue_id}
              className="rounded border border-stone-200 bg-white p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Tag color={issue.severity === 'error' ? 'red' : 'orange'}>
                  {issue.severity === 'error' ? '错误' : '警告'}
                </Tag>
                <Tag>{issue.blocking ? '阻断' : '非阻断'}</Tag>
                <Tag>{issue.scope}</Tag>
                <code className="font-mono text-xs text-stone-600">
                  {issue.code}
                </code>
              </div>
              <p className="mt-1 text-stone-800">{issue.message}</p>
              <EvidencePages
                evidence={issue.evidence}
                onSelectPage={onSelectPage}
              />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
