import { Alert, Input, Modal, Spin, Tag, message } from 'antd';
import { Chess, type Square } from 'chess.js';
import {
  type DragEvent as ReactDragEvent,
  type MouseEvent as ReactMouseEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Chessboard } from 'react-chessboard';
import useSWR from 'swr';

import { ApiError, fetchJson, requestJson } from '../logic/api/client';
import type {
  Course,
  CourseModule,
  PdfReviewCommandEnvelope,
  PdfReviewCommandRequest,
  PdfReviewDocument,
  PdfSourceEvidence,
  PdfReviewSession,
  PdfReviewSessionEnvelope,
  PdfReviewReattachPreview,
  PdfReviewRecoveryPreview,
  PdfReviewPublication,
  PdfReviewPublishRequest,
} from '../logic/api/types';
import {
  FAST_MOVE_ANIMATION_MS,
  lichessSquareStyles,
} from './boardInteraction';
import { MoveNotation } from './MoveNotation';
import {
  buildReviewSourceIndex,
  paragraphCoverage,
  needsSourceReview,
  combineCoverage,
  type SourceMoveTarget,
} from './reviewSourceCoverage';
import { ReviewSourceText, CoverageSummary } from './ReviewSourceText';
import { ReviewSourceContext, useReviewSource } from './reviewSourceContext';
import { formatMoveNotation, moveNotationText } from './moveNotation';
import {
  buildReviewMoveRows,
  buildReviewReadingFlow,
  compactReviewBlocks,
  reviewSelectionPath,
  reviewVisualSelectionRange,
  reviewMoveTurn,
} from './reviewMoveLayout';
import { parseReviewLine } from './reviewLineInput';
import type {
  AnnotatedMoveSequenceItem,
  CompactReviewBlock,
  MoveNode,
  ReviewMoveRow,
  ReviewReadingBlock,
  SequenceAnnotation,
} from './reviewMoveLayout';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

type ReviewItem = NonNullable<PdfReviewDocument['package']['items']>[number];
type MoveSequenceItem = Extract<ReviewItem, { kind: 'move_sequence' }>;
type ProseItem = Extract<ReviewItem, { kind: 'prose' }>;
type UnresolvedReviewItem = Extract<ReviewItem, { kind: 'unresolved' }>;
type EvidenceRef = ReviewItem['evidence'][number];

type AnnotationBlock = Extract<CompactReviewBlock, { kind: 'annotation' }>;
type DisplayReviewBlock =
  | CompactReviewBlock
  | {
      kind: 'annotation_group';
      key: string;
      blocks: AnnotationBlock[];
    };

function groupReviewAnnotations(
  blocks: CompactReviewBlock[],
): DisplayReviewBlock[] {
  const displayed: DisplayReviewBlock[] = [];
  let pending: AnnotationBlock[] = [];
  function flush() {
    if (pending.length >= 3) {
      displayed.push({
        kind: 'annotation_group',
        key: `comments:${pending[0].key}`,
        blocks: pending,
      });
    } else {
      displayed.push(...pending);
    }
    pending = [];
  }
  for (const block of blocks) {
    if (block.kind !== 'annotation') {
      flush();
      displayed.push(block);
      continue;
    }
    if (
      pending.length > 0 &&
      pending[0].annotation.evidence[0]?.page !==
        block.annotation.evidence[0]?.page
    )
      flush();
    pending.push(block);
  }
  flush();
  return displayed;
}

function groupReviewItems(items: ReviewItem[]): ReviewItem[][] {
  const groups: ReviewItem[][] = [];
  for (const item of items) {
    const previous = groups.at(-1);
    if (
      item.kind === 'prose' &&
      previous?.at(-1)?.kind === 'prose' &&
      previous.at(-1)?.evidence[0]?.page === item.evidence[0]?.page
    ) {
      previous.push(item);
    } else {
      groups.push([item]);
    }
  }
  return groups;
}
type ReviewCommand = PdfReviewCommandRequest['command'];
type ReviewEditOperation = Extract<
  ReviewCommand,
  { kind: 'edit' }
>['operation'];

interface BoardContext {
  sequenceId: string;
  parentNodeId: string | null;
}

interface PendingLine {
  context: BoardContext;
  startFen: string;
  moves: string[];
  san: string[];
}

interface TextEditorState {
  itemId: string;
  annotationId: string | null;
  text: string;
  textFormat: 'plain' | 'markdown' | null;
}

interface UnresolvedEditorState {
  item: UnresolvedReviewItem | ProseItem;
  asKind: 'prose' | 'annotation' | 'line';
  text: string;
  sequenceId: string;
  anchorNodeId: string;
  notation: string;
  targetNodeId: string | null;
  targetMode: 'after' | 'parallel';
  pickingTarget: boolean;
  initialFen: string;
}

interface ContextMenuAction {
  key: string;
  label: string;
  disabled?: boolean;
  danger?: boolean;
  onSelect: () => void;
}

interface ReviewContextMenuState {
  x: number;
  y: number;
  title: string;
  pages: number[];
  actions: ContextMenuAction[];
}

interface MoveSelection {
  sequenceId: string;
  anchorNodeId: string;
  baseNodeIds: string[];
  nodeIds: string[];
}

interface AttachSelection {
  sequenceId: string;
  nodeId: string;
}

interface AttachPreview {
  source: AttachSelection;
  targetSequenceId: string;
  targetNodeId: string | null;
  mode: 'after' | 'parallel';
}

const REVIEW_NODE_DRAG_TYPE = 'application/x-chess-review-node';

function reviewNodeHit(target: EventTarget | null): AttachSelection | null {
  if (!(target instanceof Element)) return null;
  const element = target.closest<HTMLElement>('[data-review-node-id]');
  const sequenceId = element?.dataset.reviewSequenceId;
  const nodeId = element?.dataset.reviewNodeId;
  return sequenceId && nodeId ? { sequenceId, nodeId } : null;
}

function reviewStartHit(target: EventTarget | null): string | null {
  if (!(target instanceof Element)) return null;
  return (
    target.closest<HTMLElement>('[data-review-sequence-start]')?.dataset
      .reviewSequenceStart ?? null
  );
}

function editHistory(events: PdfReviewSession['events']): {
  canUndo: boolean;
  canRedo: boolean;
} {
  const done: number[] = [1];
  const undone: number[] = [];
  for (const event of events) {
    if (event.kind !== 'edited') continue;
    if (event.decisions.operation === 'undo') {
      if (done.length > 1) undone.push(done.pop()!);
    } else if (event.decisions.operation === 'redo') {
      if (undone.length > 0) done.push(undone.pop()!);
    } else {
      done.push(event.resulting_version);
      undone.length = 0;
    }
  }
  return { canUndo: done.length > 1, canRedo: undone.length > 0 };
}

interface PublicationDraftSegment {
  key: string;
  sequenceId: string;
  nodeIds: string[];
  label: string;
  targetLabel: string;
  target: PdfReviewPublishRequest['segments'][number]['target'];
}

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

function isAnnotatedMoveSequence(
  item: MoveSequenceItem,
): item is AnnotatedMoveSequenceItem {
  return 'annotations' in item && 'reading_flow' in item;
}

function uniqueEvidencePages(evidence: EvidenceRef[]): number[] {
  return [...new Set(evidence.map((ref) => ref.page))];
}

export function PdfReviewPage({ runId }: { runId: string }) {
  const url = `/api/pdf-extractions/${encodeURIComponent(runId)}/review`;
  const { data, error, isLoading, mutate } = useSWR<PdfReviewDocument>(
    url,
    fetchJson,
  );

  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [onlyPendingCommentary, setOnlyPendingCommentary] = useState(false);
  const [focusedSourceMove, setFocusedSourceMove] =
    useState<SourceMoveTarget | null>(null);
  const [boardFen, setBoardFen] = useState<string>(START_FEN);
  const [selectedSquare, setSelectedSquare] = useState<string>();
  const [boardContext, setBoardContext] = useState<BoardContext | null>(null);
  const [pendingLine, setPendingLine] = useState<PendingLine | null>(null);
  const [reviewSession, setReviewSession] = useState<PdfReviewSession | null>(
    null,
  );
  const [editing, setEditing] = useState(false);
  const [commandBusy, setCommandBusy] = useState(false);
  const [recoveryPreview, setRecoveryPreview] =
    useState<PdfReviewRecoveryPreview | null>(null);
  const [showRecoveryCandidate, setShowRecoveryCandidate] = useState(false);
  const editingBeforeRecovery = useRef(false);
  const [currentDocument, setCurrentDocument] =
    useState<PdfReviewDocument | null>(null);
  const [textEditor, setTextEditor] = useState<TextEditorState | null>(null);
  const [unresolvedEditor, setUnresolvedEditor] =
    useState<UnresolvedEditorState | null>(null);
  const [unresolvedSelectedSquare, setUnresolvedSelectedSquare] =
    useState<string>();
  const [restoreFollowing, setRestoreFollowing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publicationBusy, setPublicationBusy] = useState(false);
  const [targetCourseId, setTargetCourseId] = useState('');
  const [chapterChoice, setChapterChoice] = useState('__new__');
  const [newChapterTitle, setNewChapterTitle] = useState('');
  const [subsectionChoice, setSubsectionChoice] = useState('__none__');
  const [newSubsectionTitle, setNewSubsectionTitle] = useState('');
  const [moveSelection, setMoveSelection] = useState<MoveSelection | null>(
    null,
  );
  const [dragSelecting, setDragSelecting] = useState(false);
  const dragFocusNodeId = useRef<string | null>(null);
  const [attachSelection, setAttachSelection] =
    useState<AttachSelection | null>(null);
  const [attachPreview, setAttachPreview] = useState<AttachPreview | null>(
    null,
  );
  const [attachInspection, setAttachInspection] = useState<
    | { status: 'loading' }
    | { status: 'ready'; result: PdfReviewReattachPreview }
    | { status: 'error'; message: string }
    | null
  >(null);

  const [publicationSegments, setPublicationSegments] = useState<
    PublicationDraftSegment[]
  >([]);
  const [publicationResult, setPublicationResult] =
    useState<PdfReviewPublication | null>(null);
  const initializedRunId = useRef<string | null>(null);
  const applyCommandRef = useRef<(command: ReviewCommand) => Promise<boolean>>(
    async () => false,
  );

  const { data: targetCourses = [], mutate: mutateTargetCourses } = useSWR<
    Course[]
  >(
    publishing
      ? '/api/courses?mode=traditional&status=draft&sort=title_asc'
      : null,
    fetchJson,
  );
  const { data: targetModules = [] } = useSWR<CourseModule[]>(
    publishing && targetCourseId
      ? `/api/courses/${encodeURIComponent(targetCourseId)}/modules`
      : null,
    fetchJson,
  );

  const savedDocument = currentDocument ?? data;
  const document = useMemo(
    () =>
      recoveryPreview !== null && showRecoveryCandidate && savedDocument
        ? {
            ...savedDocument,
            package: recoveryPreview.candidate,
            inspection: recoveryPreview.inspection,
          }
        : savedDocument,
    [recoveryPreview, showRecoveryCandidate, savedDocument],
  );

  const pages = document?.pages ?? [];

  const items = useMemo(() => document?.package.items ?? [], [document]);
  const { data: sourceEvidence, error: sourceError } =
    useSWR<PdfSourceEvidence>(
      document
        ? `/api/pdf-extractions/${encodeURIComponent(runId)}/source`
        : null,
      fetchJson,
      { shouldRetryOnError: false },
    );
  const sourceIndex = useMemo(
    () =>
      sourceEvidence?.evidence_status === 'ready'
        ? buildReviewSourceIndex(items, sourceEvidence)
        : null,
    [items, sourceEvidence],
  );
  const proseCoverage = useMemo(
    () =>
      new Map(
        items
          .filter((item) => item.kind === 'prose')
          .map((item) => [
            item.id,
            paragraphCoverage(item.text, item.evidence, sourceIndex),
          ]),
      ),
    [items, sourceIndex],
  );
  const pendingParagraphs = useMemo(() => {
    let count = [...proseCoverage.values()].filter(needsSourceReview).length;
    for (const item of items)
      if (item.kind === 'move_sequence' && isAnnotatedMoveSequence(item)) {
        count += (item.annotations ?? []).filter((note) =>
          needsSourceReview(
            paragraphCoverage(note.text, note.evidence, sourceIndex),
          ),
        ).length;
      }
    return count;
  }, [items, proseCoverage, sourceIndex]);

  const initialBoardFen = useMemo(() => {
    const firstSequence = items.find((item) => item.kind === 'move_sequence');
    return firstSequence && firstSequence.kind === 'move_sequence'
      ? sequenceStartFen(firstSequence)
      : START_FEN;
  }, [items]);

  useEffect(() => {
    if (document === undefined || initializedRunId.current === runId) {
      return;
    }
    // First verified document for this run identity: initialize both the
    // board and the source page. A same-run SWR revalidation keeps the
    // previous run's guard satisfied and must not reset user navigation.
    initializedRunId.current = runId;
    setBoardFen(initialBoardFen);
    setSelectedPage(document.pages[0]?.physical_page ?? null);
  }, [document, runId, initialBoardFen]);

  useEffect(() => {
    setCurrentDocument(null);
    setOnlyPendingCommentary(false);
    setFocusedSourceMove(null);
    setRecoveryPreview(null);
    setShowRecoveryCandidate(false);
    setReviewSession(null);
    setEditing(false);
    setPendingLine(null);
    setBoardContext(null);
    setUnresolvedEditor(null);
    setUnresolvedSelectedSquare(undefined);
    initializedRunId.current = null;
    setPublishing(false);
    setMoveSelection(null);
    setAttachSelection(null);
    setAttachPreview(null);
    setPublicationSegments([]);
    setPublicationResult(null);
  }, [runId]);

  useEffect(() => {
    if (attachPreview === null || reviewSession === null) {
      setAttachInspection(null);
      return;
    }
    const target = items.find(
      (item) =>
        item.kind === 'move_sequence' &&
        item.id === attachPreview.targetSequenceId,
    );
    const targetNode =
      target?.kind === 'move_sequence'
        ? target.nodes.find((node) => node.id === attachPreview.targetNodeId)
        : undefined;
    const parentNodeId =
      attachPreview.mode === 'parallel'
        ? (targetNode?.parent_id ?? null)
        : attachPreview.targetNodeId;
    let cancelled = false;
    setAttachInspection({ status: 'loading' });
    void requestJson<PdfReviewReattachPreview>(
      `/api/pdf-review-sessions/${encodeURIComponent(reviewSession.id)}/reattach-preview`,
      {
        method: 'POST',
        body: JSON.stringify({
          expected_version: reviewSession.version,
          operation: {
            kind: 'reattach_variation',
            sequence_id: attachPreview.source.sequenceId,
            node_id: attachPreview.source.nodeId,
            target_sequence_id: attachPreview.targetSequenceId,
            parent_node_id: parentNodeId,
          },
        }),
      },
    ).then(
      (result) => {
        if (!cancelled) setAttachInspection({ status: 'ready', result });
      },
      (error: unknown) => {
        if (!cancelled)
          setAttachInspection({
            status: 'error',
            message:
              error instanceof ApiError && error.status === 422
                ? '这段棋步无法从所选局面合法走出'
                : '无法预览挂接结果',
          });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [attachPreview, reviewSession, items]);

  useEffect(() => {
    if (!dragSelecting) return;
    const finish = () => setDragSelecting(false);
    window.addEventListener('mouseup', finish);
    return () => window.removeEventListener('mouseup', finish);
  }, [dragSelecting]);

  useEffect(() => {
    if (!editing || reviewSession?.status !== 'open' || commandBusy) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
      )
        return;
      const redo =
        (event.key.toLowerCase() === 'z' && event.shiftKey) ||
        event.key.toLowerCase() === 'y';
      const undo = event.key.toLowerCase() === 'z' && !event.shiftKey;
      const history = editHistory(reviewSession.events);
      if (redo && history.canRedo) {
        event.preventDefault();
        void applyCommandRef.current({ kind: 'redo' });
      } else if (undo && history.canUndo) {
        event.preventDefault();
        void applyCommandRef.current({ kind: 'undo' });
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [editing, reviewSession, commandBusy]);

  useEffect(() => {
    if (!targetCourseId && targetCourses[0]) {
      setTargetCourseId(targetCourses[0].id);
    }
  }, [targetCourseId, targetCourses]);

  const activeDescriptor =
    pages.find((page) => page.physical_page === selectedPage) ?? pages[0];

  function selectPage(physicalPage: number) {
    if (pages.some((page) => page.physical_page === physicalPage)) {
      setSelectedPage(physicalPage);
    }
  }

  const boardSquareStyles = useMemo(
    () => lichessSquareStyles(boardFen, selectedSquare, null),
    [boardFen, selectedSquare],
  );

  const acknowledgedIssueIds = useMemo(() => {
    const acknowledged = new Set<string>();
    for (const event of reviewSession?.events ?? []) {
      if (event.kind === 'edited') {
        acknowledged.clear();
      } else if (event.kind === 'acknowledged') {
        const issueIds = event.decisions.issue_ids;
        if (Array.isArray(issueIds)) {
          for (const issueId of issueIds) {
            if (typeof issueId === 'string') acknowledged.add(issueId);
          }
        }
      }
    }
    return acknowledged;
  }, [reviewSession]);

  function sequenceById(sequenceId: string): MoveSequenceItem | undefined {
    const item = items.find(
      (candidate) =>
        candidate.kind === 'move_sequence' && candidate.id === sequenceId,
    );
    return item?.kind === 'move_sequence' ? item : undefined;
  }

  function selectNode(sequence: MoveSequenceItem, node: MoveNode) {
    if (unresolvedEditor?.pickingTarget) {
      if (
        node.validation_status !== 'valid' ||
        node.fen_before === null ||
        node.fen_after === null
      ) {
        void message.warning('请选择一条已经确认合法的棋步');
        return;
      }
      setUnresolvedEditor({
        ...unresolvedEditor,
        sequenceId: sequence.id,
        anchorNodeId: node.id,
        targetNodeId: node.id,
        pickingTarget: false,
      });
      setUnresolvedSelectedSquare(undefined);
      return;
    }
    if (node.validation_status === 'valid' && node.fen_after !== null) {
      setBoardFen(node.fen_after);
      setBoardContext({ sequenceId: sequence.id, parentNodeId: node.id });
      setPendingLine(null);
      setSelectedSquare(undefined);
    }
  }

  function navigateSourceMove(target: SourceMoveTarget) {
    const sequence = sequenceById(target.sequenceId);
    const node = sequence?.nodes.find((value) => value.id === target.nodeId);
    if (!sequence || !node) return;
    selectNode(sequence, node);
    setFocusedSourceMove(target);
    if (node.evidence[0]) setSelectedPage(node.evidence[0].page);
    window.requestAnimationFrame(() => {
      const element = [
        ...globalThis.document.querySelectorAll<HTMLElement>(
          '[data-review-node-id]',
        ),
      ].find(
        (value) =>
          value.dataset.reviewSequenceId === target.sequenceId &&
          value.dataset.reviewNodeId === target.nodeId,
      );
      for (
        let parent = element?.parentElement;
        parent;
        parent = parent.parentElement
      ) {
        if (parent instanceof HTMLDetailsElement) parent.open = true;
      }
      element?.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
      element?.focus({ preventScroll: true });
    });
  }

  function selectSequenceStart(sequence: MoveSequenceItem) {
    if (unresolvedEditor?.pickingTarget) {
      setUnresolvedEditor({
        ...unresolvedEditor,
        sequenceId: sequence.id,
        anchorNodeId: '',
        targetNodeId: null,
        targetMode: 'after',
        pickingTarget: false,
      });
      setUnresolvedSelectedSquare(undefined);
      return;
    }
    setBoardFen(sequenceStartFen(sequence));
    setBoardContext({ sequenceId: sequence.id, parentNodeId: null });
    setPendingLine(null);
    setSelectedSquare(undefined);
  }

  function selectProseAnchor(item: ProseItem) {
    const anchor = item.anchor;
    if (anchor === null) {
      return;
    }
    if (anchor.kind === 'position') {
      setBoardFen(anchor.fen);
      setBoardContext(null);
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
      setBoardContext({ sequenceId: sequence.id, parentNodeId: node.id });
    }
  }

  function selectSequenceAnnotation(
    sequence: AnnotatedMoveSequenceItem,
    annotation: SequenceAnnotation,
  ) {
    const anchor = annotation.anchor;
    if (anchor === null) {
      return;
    }
    if (anchor.kind === 'position') {
      setBoardFen(anchor.fen);
      setBoardContext(null);
      return;
    }
    const node = sequence.nodes.find(
      (candidate) => candidate.id === anchor.node_id,
    );
    if (node === undefined || node.validation_status !== 'valid') {
      return;
    }
    const fen = anchor.relation === 'before' ? node.fen_before : node.fen_after;
    if (fen !== null) {
      setBoardFen(fen);
      setBoardContext({
        sequenceId: sequence.id,
        parentNodeId: anchor.relation === 'after' ? node.id : node.parent_id,
      });
    }
  }

  async function beginEditing() {
    setCommandBusy(true);
    try {
      const envelope = await requestJson<PdfReviewSessionEnvelope>(
        `/api/pdf-extractions/${encodeURIComponent(runId)}/review/session`,
        { method: 'POST' },
      );
      setReviewSession(envelope.session);
      setEditing(envelope.session.status === 'open');
      if (envelope.session.status !== 'open') {
        void message.info('该审核已经结束；重新打开后才能继续编辑');
      }
    } catch (requestError) {
      void message.error(
        requestError instanceof Error ? requestError.message : '无法开始审核',
      );
    } finally {
      setCommandBusy(false);
    }
  }

  async function applyCommand(command: ReviewCommand): Promise<boolean> {
    if (reviewSession === null) return false;
    setCommandBusy(true);
    try {
      const envelope = await requestJson<PdfReviewCommandEnvelope>(
        `/api/pdf-review-sessions/${encodeURIComponent(reviewSession.id)}/commands`,
        {
          method: 'POST',
          body: JSON.stringify({
            expected_version: reviewSession.version,
            command,
          } satisfies PdfReviewCommandRequest),
        },
      );
      setReviewSession(envelope.session);
      setCurrentDocument(envelope.document);
      await mutate(envelope.document, { revalidate: false });
      setPendingLine(null);
      setTextEditor(null);
      if (envelope.session.status !== 'open') setEditing(false);
      void message.success('审核修改已保存');
      return true;
    } catch (requestError) {
      void message.error(
        requestError instanceof Error
          ? requestError.message
          : '保存审核修改失败',
      );
      return false;
    } finally {
      setCommandBusy(false);
    }
  }

  async function previewRecovery() {
    if (reviewSession === null) return;
    setCommandBusy(true);
    try {
      const preview = await requestJson<PdfReviewRecoveryPreview>(
        `/api/pdf-review-sessions/${encodeURIComponent(reviewSession.id)}/recovery-preview`,
        {
          method: 'POST',
          body: JSON.stringify({ expected_version: reviewSession.version }),
        },
      );
      editingBeforeRecovery.current = editing;
      setEditing(false);
      setRecoveryPreview(preview);
      setShowRecoveryCandidate(true);
      setBoardContext(null);
      setPendingLine(null);
    } catch (requestError) {
      void message.error(
        requestError instanceof Error
          ? requestError.message
          : '无法根据人工修正恢复后续棋步',
      );
    } finally {
      setCommandBusy(false);
    }
  }

  function cancelRecovery() {
    setRecoveryPreview(null);
    setShowRecoveryCandidate(false);
    setEditing(editingBeforeRecovery.current);
  }

  async function saveRecovery() {
    if (recoveryPreview === null) return;
    const saved = await applyCommand({
      kind: 'recover_dependencies',
      preview_sha256: recoveryPreview.preview_sha256,
    });
    if (saved) cancelRecovery();
  }

  applyCommandRef.current = applyCommand;

  function applyEdit(operation: ReviewEditOperation) {
    return applyCommand({ kind: 'edit', operation });
  }

  function beginMoveSelection(sequence: MoveSequenceItem, node: MoveNode) {
    if (!publishing) return;
    dragFocusNodeId.current = `${sequence.id}:${node.id}`;
    setDragSelecting(true);
    setMoveSelection((current) => {
      const rangeIds = reviewVisualSelectionRange(
        sequence.nodes,
        node.id,
        node.id,
      );
      const fresh = {
        sequenceId: sequence.id,
        anchorNodeId: node.id,
        baseNodeIds: [] as string[],
        nodeIds: rangeIds,
      };
      if (current === null || current.sequenceId !== sequence.id) return fresh;
      const path = reviewSelectionPath(
        sequence.nodes,
        current.nodeIds[0],
        node.id,
      );
      if (path === null) return fresh;
      const baseNodeIds = [...new Set([...current.nodeIds, ...path])];
      const selectedIds = new Set([...baseNodeIds, ...rangeIds]);
      return {
        ...fresh,
        baseNodeIds,
        nodeIds: sequence.nodes
          .filter((move) => selectedIds.has(move.id))
          .map((move) => move.id),
      };
    });
  }

  function extendMoveSelection(sequence: MoveSequenceItem, node: MoveNode) {
    if (!publishing || !dragSelecting) return;
    const focusKey = `${sequence.id}:${node.id}`;
    if (dragFocusNodeId.current === focusKey) return;
    dragFocusNodeId.current = focusKey;
    setMoveSelection((current) => {
      if (current === null || current.sequenceId !== sequence.id)
        return current;
      if (
        reviewSelectionPath(sequence.nodes, current.anchorNodeId, node.id) ===
        null
      ) {
        return current;
      }
      const rangeIds = reviewVisualSelectionRange(
        sequence.nodes,
        current.anchorNodeId,
        node.id,
      );
      const selectedIds = new Set([...current.baseNodeIds, ...rangeIds]);
      return {
        ...current,
        nodeIds: sequence.nodes
          .filter((move) => selectedIds.has(move.id))
          .map((move) => move.id),
      };
    });
  }

  function extendMoveSelectionThroughVisibleRange(
    event: ReactMouseEvent<HTMLElement>,
  ) {
    if (!publishing || !dragSelecting || moveSelection === null) return;
    const sequence = sequenceById(moveSelection.sequenceId);
    if (sequence === undefined) return;
    const cells = [
      ...event.currentTarget.querySelectorAll<HTMLElement>(
        '[data-review-node-id][data-review-sequence-id]',
      ),
    ].filter((cell) => cell.dataset.reviewSequenceId === sequence.id);
    const anchor = cells.find(
      (cell) => cell.dataset.reviewNodeId === moveSelection.anchorNodeId,
    );
    if (anchor === undefined) return;
    const anchorBounds = anchor.getBoundingClientRect();
    const anchorY = (anchorBounds.top + anchorBounds.bottom) / 2;
    const lowY = Math.min(anchorY, event.clientY);
    const highY = Math.max(anchorY, event.clientY);
    const covered = cells.filter((cell) => {
      const bounds = cell.getBoundingClientRect();
      const centerY = (bounds.top + bounds.bottom) / 2;
      return centerY >= lowY && centerY <= highY;
    });
    const focus = event.clientY >= anchorY ? covered.at(-1) : covered[0];
    const node = sequence.nodes.find(
      (candidate) => candidate.id === focus?.dataset.reviewNodeId,
    );
    if (node !== undefined) extendMoveSelection(sequence, node);
  }

  async function createTargetBook() {
    const title = window.prompt('新书名称')?.trim();
    if (!title) return;
    try {
      const created = await requestJson<Course>('/api/courses', {
        method: 'POST',
        body: JSON.stringify({ title, mode: 'traditional' }),
      });
      await mutateTargetCourses((current) => [...(current ?? []), created], {
        revalidate: false,
      });
      setTargetCourseId(created.id);
      setPublicationSegments([]);
      void message.success('书籍草稿已创建');
    } catch (requestError) {
      void message.error(
        requestError instanceof Error ? requestError.message : '创建书籍失败',
      );
    }
  }

  function addPublicationSegment() {
    if (moveSelection === null) {
      void message.warning('请先在棋谱上拖拽选择棋步');
      return;
    }
    const sequence = sequenceById(moveSelection.sequenceId);
    if (sequence === undefined) return;
    const chapter =
      chapterChoice === '__new__'
        ? newChapterTitle.trim()
          ? ({ kind: 'new', title: newChapterTitle.trim() } as const)
          : null
        : ({ kind: 'existing', module_id: chapterChoice } as const);
    if (chapter === null) {
      void message.warning('请选择章节或填写新章节标题');
      return;
    }
    const subsection =
      subsectionChoice === '__none__'
        ? null
        : subsectionChoice === '__new__'
          ? newSubsectionTitle.trim()
            ? ({ kind: 'new', title: newSubsectionTitle.trim() } as const)
            : undefined
          : ({ kind: 'existing', module_id: subsectionChoice } as const);
    if (subsection === undefined) {
      void message.warning('请填写新小节标题');
      return;
    }
    const selectedNodes = sequence.nodes.filter((node) =>
      moveSelection.nodeIds.includes(node.id),
    );
    const chapterLabel =
      chapter.kind === 'new'
        ? chapter.title
        : (targetModules.find((item) => item.id === chapter.module_id)?.title ??
          '已有章节');
    const subsectionLabel =
      subsection === null
        ? null
        : subsection.kind === 'new'
          ? subsection.title
          : (targetModules.find((item) => item.id === subsection.module_id)
              ?.title ?? '已有小节');
    setPublicationSegments((current) => [
      ...current,
      {
        key: `${sequence.id}:${moveSelection.nodeIds.join(':')}:${current.length}`,
        sequenceId: sequence.id,
        nodeIds: moveSelection.nodeIds,
        label: `${sequence.title ?? '棋谱'} · ${selectedNodes[0]?.move_text ?? ''}–${selectedNodes.at(-1)?.move_text ?? ''}`,
        targetLabel: subsectionLabel
          ? `${chapterLabel} / ${subsectionLabel}`
          : chapterLabel,
        target: { chapter, subsection },
      },
    ]);
    setMoveSelection(null);
  }

  async function publishPlan() {
    if (
      reviewSession === null ||
      reviewSession.status !== 'approved' ||
      !targetCourseId ||
      publicationSegments.length === 0
    ) {
      return;
    }
    setPublicationBusy(true);
    try {
      const result = await requestJson<PdfReviewPublication>(
        `/api/pdf-review-sessions/${encodeURIComponent(reviewSession.id)}/publications`,
        {
          method: 'POST',
          body: JSON.stringify({
            expected_version: reviewSession.version,
            target_course_id: targetCourseId,
            mapping_version: 'review-course-publication/1.1',
            segments: publicationSegments.map((segment) => ({
              sequence_id: segment.sequenceId,
              node_ids: segment.nodeIds,
              target: segment.target,
            })),
          } satisfies PdfReviewPublishRequest),
        },
      );
      setPublicationResult(result);
      void message.success(
        result.replayed ? '该发布计划已完成' : '已发布到学习资料',
      );
    } catch (requestError) {
      void message.error(
        requestError instanceof Error ? requestError.message : '发布失败',
      );
    } finally {
      setPublicationBusy(false);
    }
  }

  function submitBoardMove(source: string, target: string): boolean {
    if (!editing || boardContext === null || activeDescriptor === undefined) {
      return false;
    }
    const game = new Chess(boardFen);
    let move;
    try {
      const piece = game.get(source as Square);
      const promotes =
        piece?.type === 'p' && (target.endsWith('1') || target.endsWith('8'));
      const requestedPromotion = promotes
        ? window
            .prompt('升变为 q（后）、r（车）、b（象）或 n（马）', 'q')
            ?.trim()
            .toLowerCase()
        : undefined;
      if (
        promotes &&
        requestedPromotion !== 'q' &&
        requestedPromotion !== 'r' &&
        requestedPromotion !== 'b' &&
        requestedPromotion !== 'n'
      ) {
        return false;
      }
      move = game.move({
        from: source,
        to: target,
        promotion: requestedPromotion,
      });
    } catch {
      return false;
    }
    if (!move) return false;
    const uci = `${source}${target}${move.promotion ?? ''}`;

    if (pendingLine === null) {
      const sequence = sequenceById(boardContext.sequenceId);
      const existing = sequence?.nodes.find(
        (node) =>
          node.parent_id === boardContext.parentNodeId &&
          node.validation_status === 'valid' &&
          node.uci_candidate === uci,
      );
      if (sequence !== undefined && existing !== undefined) {
        selectNode(sequence, existing);
        return true;
      }
      setPendingLine({
        context: boardContext,
        startFen: boardFen,
        moves: [uci],
        san: [move.san],
      });
    } else {
      setPendingLine({
        ...pendingLine,
        moves: [...pendingLine.moves, uci],
        san: [...pendingLine.san, move.san],
      });
    }
    setBoardFen(game.fen());
    setSelectedSquare(undefined);
    return true;
  }

  function selectOwnPiece(square: string) {
    try {
      const game = new Chess(boardFen);
      const piece = game.get(square as Square);
      setSelectedSquare(piece?.color === game.turn() ? square : undefined);
    } catch {
      setSelectedSquare(undefined);
    }
  }

  function onSquareClick(square: string) {
    if (!editing) return;
    if (!selectedSquare) {
      selectOwnPiece(square);
      return;
    }
    if (selectedSquare === square) {
      setSelectedSquare(undefined);
      return;
    }
    if (!submitBoardMove(selectedSquare, square)) selectOwnPiece(square);
  }

  function cancelPendingLine() {
    if (pendingLine !== null) setBoardFen(pendingLine.startFen);
    setPendingLine(null);
    setSelectedSquare(undefined);
  }

  function savePendingLine() {
    if (pendingLine === null || activeDescriptor === undefined) return;
    void applyEdit({
      kind: 'add_line',
      sequence_id: pendingLine.context.sequenceId,
      parent_node_id: pendingLine.context.parentNodeId,
      moves: pendingLine.moves,
      evidence_page: activeDescriptor.physical_page,
    });
  }

  function deleteFromHere(sequence: MoveSequenceItem, node: MoveNode) {
    if (!window.confirm(`从 ${node.move_text} 开始删除这条分支及全部后续？`)) {
      return;
    }
    if (node.fen_before !== null) setBoardFen(node.fen_before);
    setBoardContext({
      sequenceId: sequence.id,
      parentNodeId: node.parent_id,
    });
    void applyEdit({
      kind: 'delete_subtree',
      sequence_id: sequence.id,
      node_id: node.id,
    });
  }

  function promoteVariation(sequence: MoveSequenceItem, node: MoveNode) {
    void applyEdit({
      kind: 'promote_variation',
      sequence_id: sequence.id,
      node_id: node.id,
    });
  }

  function makeMainline(sequence: MoveSequenceItem, node: MoveNode) {
    void applyEdit({
      kind: 'make_mainline',
      sequence_id: sequence.id,
      node_id: node.id,
    });
  }

  function setInitialPosition(sequence: MoveSequenceItem) {
    const fen = window.prompt(
      '输入该棋谱的初始 FEN（棋盘图示局面）',
      sequence.initial_position.kind === 'fen'
        ? sequence.initial_position.fen
        : START_FEN,
    );
    if (fen === null || fen.trim() === '') return;
    void applyEdit({
      kind: 'set_initial_position',
      sequence_id: sequence.id,
      fen: fen.trim(),
    });
  }

  function reattachVariation(sequence: MoveSequenceItem, node: MoveNode) {
    setAttachSelection({ sequenceId: sequence.id, nodeId: node.id });
    setAttachPreview(null);
    void message.info('现在点击目标棋步，或把整段变化拖到目标棋步');
  }

  function chooseAttachTarget(
    source: AttachSelection,
    targetSequenceId: string,
    targetNodeId: string | null,
  ) {
    if (
      source.sequenceId === targetSequenceId &&
      source.nodeId === targetNodeId
    ) {
      return;
    }
    setAttachSelection(source);
    setAttachPreview({ source, targetSequenceId, targetNodeId, mode: 'after' });
  }

  function onReviewClickCapture(event: ReactMouseEvent<HTMLElement>) {
    if (!editing || attachSelection === null || publishing) return;
    const targetNode = reviewNodeHit(event.target);
    const targetStart = reviewStartHit(event.target);
    if (targetNode === null && targetStart === null) return;
    event.preventDefault();
    event.stopPropagation();
    chooseAttachTarget(
      attachSelection,
      targetNode?.sequenceId ?? targetStart!,
      targetNode?.nodeId ?? null,
    );
  }

  function onReviewDragStartCapture(event: ReactDragEvent<HTMLElement>) {
    if (!editing || publishing) return;
    const source = reviewNodeHit(event.target);
    if (source === null) return;
    event.dataTransfer.setData(REVIEW_NODE_DRAG_TYPE, JSON.stringify(source));
    event.dataTransfer.effectAllowed = 'move';
    // The board's window handlers must not cancel score-node dragging.
    event.stopPropagation();
  }

  function onReviewDragOverCapture(event: ReactDragEvent<HTMLElement>) {
    if (
      editing &&
      !publishing &&
      event.dataTransfer.types.includes(REVIEW_NODE_DRAG_TYPE) &&
      (reviewNodeHit(event.target) !== null ||
        reviewStartHit(event.target) !== null)
    ) {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      event.stopPropagation();
    }
  }

  function onReviewDropCapture(event: ReactDragEvent<HTMLElement>) {
    if (!editing || publishing) return;
    const targetNode = reviewNodeHit(event.target);
    const targetStart = reviewStartHit(event.target);
    if (targetNode === null && targetStart === null) return;
    const raw = event.dataTransfer.getData(REVIEW_NODE_DRAG_TYPE);
    if (!raw) return;
    event.preventDefault();
    event.stopPropagation();
    try {
      const source = JSON.parse(raw) as AttachSelection;
      if (
        typeof source.sequenceId !== 'string' ||
        typeof source.nodeId !== 'string'
      )
        return;
      chooseAttachTarget(
        source,
        targetNode?.sequenceId ?? targetStart!,
        targetNode?.nodeId ?? null,
      );
    } catch {
      void message.error('无法识别拖动的分支');
    }
  }

  function saveAttachPreview() {
    if (attachPreview === null) return;
    const target = sequenceById(attachPreview.targetSequenceId);
    const targetNode = target?.nodes.find(
      (node) => node.id === attachPreview.targetNodeId,
    );
    const parentNodeId =
      attachPreview.mode === 'parallel'
        ? (targetNode?.parent_id ?? null)
        : attachPreview.targetNodeId;
    void applyEdit({
      kind: 'reattach_variation',
      sequence_id: attachPreview.source.sequenceId,
      node_id: attachPreview.source.nodeId,
      target_sequence_id: attachPreview.targetSequenceId,
      parent_node_id: parentNodeId,
    });
    setAttachPreview(null);
    setAttachSelection(null);
  }

  function resolveUnresolved(
    item: UnresolvedReviewItem | ProseItem,
    asKind: UnresolvedEditorState['asKind'] = 'prose',
  ) {
    setSelectedPage(item.evidence[0]?.page ?? null);
    setUnresolvedSelectedSquare(undefined);
    setRestoreFollowing(false);
    setAttachSelection(null);
    setAttachPreview(null);
    const sourceText =
      item.kind === 'prose' ? item.text : (item.raw_text ?? item.details ?? '');
    setUnresolvedEditor({
      item,
      asKind,
      text: item.kind === 'prose' && asKind === 'line' ? '' : sourceText,
      sequenceId: '',
      anchorNodeId: '',
      targetNodeId: null,
      targetMode: 'after',
      pickingTarget: asKind === 'line',
      notation: item.kind === 'prose' ? item.text : (item.raw_text ?? ''),
      initialFen: START_FEN,
    });
  }

  const unresolvedSequence = unresolvedEditor?.sequenceId
    ? sequenceById(unresolvedEditor.sequenceId)
    : undefined;
  const unresolvedTarget = unresolvedSequence?.nodes.find(
    (node) => node.id === unresolvedEditor?.targetNodeId,
  );
  const unresolvedStartFen =
    unresolvedEditor?.asKind === 'line'
      ? unresolvedSequence
        ? unresolvedTarget
          ? unresolvedEditor.targetMode === 'parallel'
            ? unresolvedTarget.fen_before
            : unresolvedTarget.fen_after
          : sequenceStartFen(unresolvedSequence)
        : unresolvedEditor.initialFen
      : null;
  const unresolvedPreview =
    unresolvedStartFen !== null && unresolvedEditor?.asKind === 'line'
      ? parseReviewLine(unresolvedEditor.notation, unresolvedStartFen)
      : null;
  const followingCandidates: {
    item: UnresolvedReviewItem;
    moves: string[];
    san: string[];
    nags: (number | null)[];
  }[] = [];
  if (
    unresolvedEditor?.asKind === 'line' &&
    unresolvedEditor.sequenceId &&
    unresolvedPreview?.ok &&
    unresolvedPreview.uci.length > 0
  ) {
    const index = items.findIndex(
      (item) => item.id === unresolvedEditor.item.id,
    );
    let fen = unresolvedPreview.fenAfter;
    for (const candidate of items.slice(index + 1)) {
      if (
        candidate.kind !== 'unresolved' ||
        candidate.reason_code !== 'semantic_chunk_failed' ||
        !candidate.raw_text
      )
        break;
      const parsed = parseReviewLine(candidate.raw_text, fen);
      if (!parsed.ok || parsed.uci.length === 0) break;
      followingCandidates.push({
        item: candidate,
        moves: parsed.uci,
        san: parsed.san,
        nags: parsed.nags,
      });
      fen = parsed.fenAfter;
    }
  }

  const unresolvedBoardFen = unresolvedPreview?.ok
    ? unresolvedPreview.fenAfter
    : unresolvedPreview?.message === '起点局面无效'
      ? null
      : unresolvedStartFen;

  function addUnresolvedBoardMove(source: string, target: string): boolean {
    if (unresolvedBoardFen === null || unresolvedEditor === null) return false;
    try {
      const game = new Chess(unresolvedBoardFen);
      const move = game.move({ from: source, to: target, promotion: 'q' });
      setUnresolvedEditor({
        ...unresolvedEditor,
        notation: unresolvedPreview?.ok
          ? `${unresolvedEditor.notation.trim()} ${move.san}`.trim()
          : move.san,
      });
      setUnresolvedSelectedSquare(undefined);
      return true;
    } catch {
      return false;
    }
  }

  function clickUnresolvedBoardSquare(square: string) {
    if (unresolvedBoardFen === null) return;
    if (!unresolvedSelectedSquare) {
      const game = new Chess(unresolvedBoardFen);
      const piece = game.get(square as Square);
      setUnresolvedSelectedSquare(
        piece?.color === game.turn() ? square : undefined,
      );
      return;
    }
    if (!addUnresolvedBoardMove(unresolvedSelectedSquare, square)) {
      setUnresolvedSelectedSquare(undefined);
    }
  }

  async function saveUnresolvedEditor() {
    if (unresolvedEditor === null) return;
    const { item, asKind, text, sequenceId, anchorNodeId, initialFen } =
      unresolvedEditor;
    if (asKind !== 'line' && !text.trim()) {
      void message.warning('请保留或填写来源文字');
      return;
    }
    if (asKind === 'annotation' && !sequenceId) {
      void message.warning('请点选注释所属棋步');
      return;
    }
    if (
      asKind === 'line' &&
      (unresolvedPreview?.ok !== true || unresolvedPreview.uci.length === 0)
    ) {
      void message.warning('请选择起点并输入能从该局面走出的棋步');
      return;
    }
    const parentNodeId =
      unresolvedEditor.targetMode === 'parallel' && unresolvedTarget
        ? unresolvedTarget.parent_id
        : unresolvedEditor.targetNodeId;
    const saved = await applyEdit({
      kind: 'resolve_unresolved',
      item_id: item.id,
      as_kind: asKind,
      text:
        asKind === 'line'
          ? item.kind === 'prose' && text.trim()
            ? text.trim()
            : null
          : text.trim(),
      sequence_id: asKind === 'prose' ? null : sequenceId || null,
      anchor_node_id:
        asKind === 'prose'
          ? null
          : asKind === 'line'
            ? parentNodeId
            : anchorNodeId || null,
      moves:
        asKind === 'line' && unresolvedPreview?.ok ? unresolvedPreview.uci : [],
      ...(asKind === 'line' &&
      unresolvedPreview?.ok &&
      unresolvedPreview.nags.some((nag) => nag !== null)
        ? { nags: unresolvedPreview.nags }
        : {}),
      initial_fen: asKind === 'line' && !sequenceId ? initialFen.trim() : null,
      ...(asKind === 'line' &&
      restoreFollowing &&
      followingCandidates.length > 0
        ? {
            following: followingCandidates.map(({ item, moves, nags }) => ({
              item_id: item.id,
              moves,
              ...(nags.some((nag) => nag !== null) ? { nags } : {}),
            })),
          }
        : {}),
    });
    if (saved) setUnresolvedEditor(null);
  }

  function setNag(sequence: MoveSequenceItem, node: MoveNode) {
    const entered = window.prompt(
      '输入 NAG 数字 0–255；留空表示清除',
      reviewNodeDisplay(node).nags[0]?.toString() ?? '',
    );
    if (entered === null) return;
    const nag = entered.trim() === '' ? null : Number(entered);
    if (nag !== null && (!Number.isInteger(nag) || nag < 0 || nag > 255)) {
      void message.error('NAG 必须是 0–255 的整数');
      return;
    }
    void applyEdit({
      kind: 'set_nag',
      sequence_id: sequence.id,
      node_id: node.id,
      nag,
    });
  }

  function openTextEditor(
    itemId: string,
    annotationId: string | null,
    text: string,
    textFormat: 'plain' | 'markdown' | null,
  ) {
    setTextEditor({ itemId, annotationId, text, textFormat });
  }

  function saveTextEditor() {
    if (textEditor === null) return;
    void applyEdit({
      kind: 'edit_text',
      item_id: textEditor.itemId,
      annotation_id: textEditor.annotationId,
      text: textEditor.text,
      text_format: textEditor.textFormat,
    });
  }

  function acknowledgeIssues(issueIds: string[]) {
    if (issueIds.length === 0) return;
    void applyCommand({ kind: 'acknowledge', issue_ids: issueIds });
  }

  function rejectReview() {
    const reason = window.prompt('请简要说明拒绝原因');
    if (reason === null || reason.trim() === '') return;
    void applyCommand({ kind: 'reject', reason });
  }

  function reopenReview() {
    void applyCommand({ kind: 'reopen', reason: null });
  }

  function excludeItem(itemId: string) {
    if (
      !window.confirm(
        '确认从当前审核修订中排除这项内容？原始提取结果不会被修改。',
      )
    ) {
      return;
    }
    void applyEdit({ kind: 'exclude_item', item_id: itemId });
  }

  function detachPositionAnchor(issueId: string) {
    if (
      !window.confirm(
        '保留这段文字，但取消它与无法定位局面的关联吗？原始提取结果不会被修改。',
      )
    ) {
      return;
    }
    void applyEdit({ kind: 'detach_position_anchor', issue_id: issueId });
  }

  if (isLoading) {
    return (
      <div role="status" aria-busy="true" className="p-8 text-stone-600">
        <Spin description="正在加载审核资料" />
      </div>
    );
  }

  if (error !== undefined || document === undefined) {
    return (
      <Alert
        type="error"
        showIcon
        title={reviewErrorMessage(error)}
        role="alert"
      />
    );
  }

  const history = editHistory(reviewSession?.events ?? []);
  const attachSourceSequence = attachPreview
    ? sequenceById(attachPreview.source.sequenceId)
    : undefined;
  const attachSourceNode = attachSourceSequence?.nodes.find(
    (node) => node.id === attachPreview?.source.nodeId,
  );
  const attachTargetSequence = attachPreview
    ? sequenceById(attachPreview.targetSequenceId)
    : undefined;
  const attachTargetNode = attachTargetSequence?.nodes.find(
    (node) => node.id === attachPreview?.targetNodeId,
  );
  const attachParentNodeId =
    attachPreview?.mode === 'parallel'
      ? (attachTargetNode?.parent_id ?? null)
      : (attachPreview?.targetNodeId ?? null);
  const attachParentNode = attachTargetSequence?.nodes.find(
    (node) => node.id === attachParentNodeId,
  );
  const attachBoardFen = attachTargetSequence
    ? (attachParentNode?.fen_after ?? sequenceStartFen(attachTargetSequence))
    : START_FEN;
  const attachDescendantCount =
    attachSourceSequence && attachSourceNode
      ? (() => {
          const descendants = new Set([attachSourceNode.id]);
          for (let changed = true; changed;) {
            changed = false;
            for (const node of attachSourceSequence.nodes) {
              if (
                node.parent_id &&
                descendants.has(node.parent_id) &&
                !descendants.has(node.id)
              ) {
                descendants.add(node.id);
                changed = true;
              }
            }
          }
          return descendants.size;
        })()
      : 0;

  const unacknowledgedWarnings = document.inspection.issues.filter(
    (issue) => !issue.blocking && !acknowledgedIssueIds.has(issue.issue_id),
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 px-6">
        {reviewSession === null ? (
          <button
            type="button"
            disabled={commandBusy}
            onClick={() => void beginEditing()}
            className="rounded bg-emerald-800 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            开始编辑审核
          </button>
        ) : (
          <>
            <Tag
              color={
                reviewSession.status === 'open'
                  ? 'blue'
                  : reviewSession.status === 'approved'
                    ? 'green'
                    : 'red'
              }
            >
              {reviewSession.status === 'open'
                ? `审核中 · 版本 ${reviewSession.version}`
                : reviewSession.status === 'approved'
                  ? `已批准 · 版本 ${reviewSession.version}`
                  : `已拒绝 · 版本 ${reviewSession.version}`}
            </Tag>
            {reviewSession.status === 'open' ? (
              <>
                <button
                  type="button"
                  disabled={recoveryPreview !== null}
                  onClick={() => setEditing((value) => !value)}
                  className="rounded border border-stone-300 bg-white px-3 py-1.5 text-sm"
                >
                  {editing ? '暂停编辑' : '继续编辑'}
                </button>
                <button
                  type="button"
                  disabled={commandBusy || recoveryPreview !== null}
                  onClick={() => void previewRecovery()}
                  className="rounded border border-emerald-600 bg-white px-3 py-1.5 text-sm text-emerald-800 disabled:opacity-40"
                >
                  根据人工修正恢复后续
                </button>
                <button
                  type="button"
                  disabled={
                    commandBusy || recoveryPreview !== null || !history.canUndo
                  }
                  onClick={() => void applyCommand({ kind: 'undo' })}
                  className="rounded border border-stone-300 bg-white px-3 py-1.5 text-sm disabled:opacity-40"
                >
                  撤销
                </button>
                <button
                  type="button"
                  disabled={
                    commandBusy || recoveryPreview !== null || !history.canRedo
                  }
                  onClick={() => void applyCommand({ kind: 'redo' })}
                  className="rounded border border-stone-300 bg-white px-3 py-1.5 text-sm disabled:opacity-40"
                >
                  恢复
                </button>
                <button
                  type="button"
                  disabled={
                    commandBusy ||
                    recoveryPreview !== null ||
                    unacknowledgedWarnings.length === 0
                  }
                  onClick={() =>
                    acknowledgeIssues(
                      unacknowledgedWarnings.map((issue) => issue.issue_id),
                    )
                  }
                  className="rounded border border-stone-300 bg-white px-3 py-1.5 text-sm disabled:opacity-40"
                >
                  确认全部警告
                </button>
                <button
                  type="button"
                  disabled={
                    commandBusy ||
                    recoveryPreview !== null ||
                    document.inspection.blocking_issue_count > 0 ||
                    unacknowledgedWarnings.length > 0
                  }
                  onClick={() => void applyCommand({ kind: 'approve' })}
                  className="rounded bg-emerald-800 px-3 py-1.5 text-sm text-white disabled:opacity-40"
                >
                  批准
                </button>
                <button
                  type="button"
                  disabled={commandBusy || recoveryPreview !== null}
                  onClick={rejectReview}
                  className="rounded border border-red-300 bg-white px-3 py-1.5 text-sm text-red-700"
                >
                  拒绝
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  disabled={commandBusy}
                  onClick={reopenReview}
                  className="rounded border border-stone-300 bg-white px-3 py-1.5 text-sm"
                >
                  重新打开
                </button>
                {reviewSession.status === 'approved' ? (
                  <button
                    type="button"
                    onClick={() => setPublishing((value) => !value)}
                    className="rounded bg-emerald-800 px-3 py-1.5 text-sm text-white"
                  >
                    {publishing ? '收起发布编排' : '编排发布'}
                  </button>
                ) : null}
              </>
            )}
          </>
        )}
        {editing ? (
          <span className="text-sm text-stone-600">
            点击棋谱选择局面，然后直接在棋盘走棋
          </span>
        ) : null}
      </div>
      {recoveryPreview !== null ? (
        <div className="mx-6 space-y-2 rounded border border-emerald-400 bg-emerald-50 p-3 text-sm">
          <div className="font-semibold">
            依赖恢复预览 · 新增 {recoveryPreview.added_moves.length} 招，解决{' '}
            {recoveryPreview.retired_issue_count} 条待审，保留{' '}
            {recoveryPreview.preserved_manual_moves} 招人工补录
          </div>
          <div>
            依据你的改挂：{recoveryPreview.corrected_entries.join('、')}
          </div>
          {recoveryPreview.conflicts.length > 0 ? (
            <div className="text-amber-800">
              有 {recoveryPreview.conflicts.length} 处未自动合并：
              {recoveryPreview.conflicts.slice(0, 3).join('；')}
              。这些位置仍保留原审核内容。
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setShowRecoveryCandidate((value) => !value)}
              className="rounded border border-stone-300 bg-white px-3 py-1"
            >
              {showRecoveryCandidate ? '对照原审核结果' : '查看恢复候选'}
            </button>
            <button
              type="button"
              disabled={commandBusy}
              onClick={() => void saveRecovery()}
              className="rounded bg-emerald-800 px-3 py-1 text-white disabled:opacity-40"
            >
              确认恢复
            </button>
            <button
              type="button"
              disabled={commandBusy}
              onClick={cancelRecovery}
              className="rounded border border-stone-300 bg-white px-3 py-1"
            >
              取消
            </button>
          </div>
          <details>
            <summary>查看本次恢复的棋步</summary>
            <div className="max-h-40 overflow-y-auto">
              {recoveryPreview.added_moves.map((move) => (
                <span
                  key={`${move.sequence_id}:${move.node_id}`}
                  className="mr-3 inline-block"
                >
                  第 {move.page} 页 · {move.move_text}
                </span>
              ))}
            </div>
          </details>
        </div>
      ) : null}
      {attachSelection !== null && editing ? (
        <div className="mx-6 flex items-center gap-3 rounded border border-blue-300 bg-blue-50 px-3 py-2 text-sm">
          <span>
            已选择整段变化：点击目标棋步，或拖动棋步到目标位置。保存前可选择接在后面或作为并列变化。
          </span>
          <button
            type="button"
            onClick={() => {
              setAttachSelection(null);
              setAttachPreview(null);
            }}
            className="underline"
          >
            取消
          </button>
        </div>
      ) : null}
      {unresolvedEditor?.pickingTarget && editing ? (
        <div className="sticky top-0 z-10 mx-6 flex items-center gap-3 rounded border border-blue-300 bg-blue-50 px-3 py-2 text-sm">
          <span>
            请在棋谱中点选目标棋步；选谱头的“回到初始局面”可从第一步前接续。
          </span>
          <button
            type="button"
            onClick={() =>
              setUnresolvedEditor({ ...unresolvedEditor, pickingTarget: false })
            }
            className="underline"
          >
            先编辑文字
          </button>
          {unresolvedEditor.asKind === 'line' ? (
            <button
              type="button"
              onClick={() =>
                setUnresolvedEditor({
                  ...unresolvedEditor,
                  sequenceId: '',
                  targetNodeId: null,
                  pickingTarget: false,
                })
              }
              className="underline"
            >
              独立新棋谱
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setUnresolvedEditor(null)}
            className="underline"
          >
            取消
          </button>
        </div>
      ) : null}
      {publishing ? (
        <section
          aria-label="发布计划"
          className="mx-6 rounded-md border border-emerald-200 bg-emerald-50 p-3"
        >
          <div className="flex flex-wrap items-end gap-3">
            <label className="grid gap-1 text-sm">
              <span className="font-medium">书</span>
              <select
                aria-label="发布到书"
                value={targetCourseId}
                onChange={(event) => {
                  setTargetCourseId(event.target.value);
                  setPublicationSegments([]);
                  setChapterChoice('__new__');
                  setSubsectionChoice('__none__');
                }}
                className="min-w-52 rounded border border-stone-300 bg-white px-2 py-1.5"
              >
                <option value="">选择书籍草稿</option>
                {targetCourses.map((course) => (
                  <option key={course.id} value={course.id}>
                    {course.title}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => void createTargetBook()}
              className="rounded border border-stone-300 bg-white px-2 py-1.5 text-sm"
            >
              新建书籍
            </button>
            <label className="grid gap-1 text-sm">
              <span className="font-medium">章节</span>
              <select
                aria-label="目标章节"
                value={chapterChoice}
                onChange={(event) => {
                  setChapterChoice(event.target.value);
                  setSubsectionChoice('__none__');
                }}
                className="min-w-48 rounded border border-stone-300 bg-white px-2 py-1.5"
              >
                <option value="__new__">新建章节</option>
                {targetModules
                  .filter((item) => item.parent_id === null)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title}
                    </option>
                  ))}
              </select>
            </label>
            {chapterChoice === '__new__' ? (
              <Input
                aria-label="新章节标题"
                value={newChapterTitle}
                onChange={(event) => setNewChapterTitle(event.target.value)}
                placeholder="章节标题"
                className="max-w-52"
              />
            ) : null}
            <label className="grid gap-1 text-sm">
              <span className="font-medium">例局 / 理论（可选）</span>
              <select
                aria-label="目标小节"
                value={subsectionChoice}
                onChange={(event) => setSubsectionChoice(event.target.value)}
                className="min-w-52 rounded border border-stone-300 bg-white px-2 py-1.5"
              >
                <option value="__none__">直接放入章节</option>
                <option value="__new__">新建小节</option>
                {chapterChoice !== '__new__'
                  ? targetModules
                      .filter((item) => item.parent_id === chapterChoice)
                      .map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.title}
                        </option>
                      ))
                  : null}
              </select>
            </label>
            {subsectionChoice === '__new__' ? (
              <Input
                aria-label="新小节标题"
                value={newSubsectionTitle}
                onChange={(event) => setNewSubsectionTitle(event.target.value)}
                placeholder="例局或理论标题"
                className="max-w-52"
              />
            ) : null}
            <button
              type="button"
              onClick={addPublicationSegment}
              className="rounded border border-emerald-700 bg-white px-3 py-1.5 text-sm text-emerald-900"
            >
              加入当前选择
            </button>
          </div>
          <p className="mt-2 text-sm text-stone-600">
            在右侧棋谱从上往下拖选范围；范围内的棋步及主线所附属的支线会一起选中。
            同一棋局可多次拖选叠加；加入当前选择后，可再选择片段放入其他章节或小节。
            {moveSelection !== null
              ? ` 当前已选 ${moveSelection.nodeIds.length} 个半回合。`
              : ''}
            {moveSelection !== null ? (
              <button
                type="button"
                onClick={() => setMoveSelection(null)}
                className="ml-2 text-emerald-800 underline"
              >
                清空当前选择
              </button>
            ) : null}
          </p>
          {publicationSegments.length > 0 ? (
            <ol className="mt-2 grid gap-1 pl-5 text-sm">
              {publicationSegments.map((segment, index) => (
                <li key={segment.key}>
                  {segment.label} → {segment.targetLabel}（
                  {segment.nodeIds.length} 个半回合）
                  <button
                    type="button"
                    onClick={() =>
                      setPublicationSegments((current) =>
                        current.filter((_, itemIndex) => itemIndex !== index),
                      )
                    }
                    className="ml-2 text-red-700"
                  >
                    移除
                  </button>
                </li>
              ))}
            </ol>
          ) : null}
          <div className="mt-3 flex items-center gap-3">
            <button
              type="button"
              disabled={
                publicationBusy ||
                !targetCourseId ||
                publicationSegments.length === 0
              }
              onClick={() => void publishPlan()}
              className="rounded bg-emerald-800 px-3 py-1.5 text-sm text-white disabled:opacity-40"
            >
              {publicationBusy ? '正在发布…' : '原子发布全部片段'}
            </button>
            {publicationResult !== null ? (
              <a
                href={`/learn/${publicationResult.target_course_id}`}
                className="text-sm text-emerald-800 underline"
              >
                打开已发布书籍
              </a>
            ) : null}
          </div>
        </section>
      ) : null}
      <div className="grid grid-cols-1 gap-6 px-6 pb-6 lg:h-[calc(100vh-12rem)] lg:grid-cols-3 lg:overflow-hidden">
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
                  page.physical_page ===
                  (activeDescriptor?.physical_page ?? null)
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
              arePiecesDraggable={editing && boardContext !== null}
              onPieceDrop={(source, target) => submitBoardMove(source, target)}
              onPieceDragBegin={(_, source) => selectOwnPiece(source)}
              onPieceDragEnd={() => setSelectedSquare(undefined)}
              onSquareClick={onSquareClick}
              customSquareStyles={boardSquareStyles}
              customBoardStyle={{
                borderRadius: '8px',
                boxShadow: '0 12px 30px rgba(28,25,23,.16)',
              }}
            />
            {editing && boardContext === null ? (
              <Alert
                className="mt-3"
                type="info"
                title="先点击一条棋谱的起点或棋步，再从该局面录入"
              />
            ) : null}
            {pendingLine !== null ? (
              <div className="mt-3 rounded border border-emerald-300 bg-emerald-50 p-3">
                <p className="text-sm text-stone-800">
                  待保存线路：{pendingLine.san.join(' ')} · 来源第{' '}
                  {activeDescriptor?.physical_page} 页
                </p>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    disabled={commandBusy}
                    onClick={savePendingLine}
                    className="rounded bg-emerald-800 px-3 py-1 text-sm text-white"
                  >
                    保存线路
                  </button>
                  <button
                    type="button"
                    disabled={commandBusy}
                    onClick={cancelPendingLine}
                    className="rounded border border-stone-300 bg-white px-3 py-1 text-sm"
                  >
                    撤销本次录入
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </section>

        <ReviewSourceContext.Provider
          value={{
            index: sourceIndex,
            onlyPending: onlyPendingCommentary,
            focused: focusedSourceMove,
            navigate: navigateSourceMove,
          }}
        >
          <section
            aria-label="候选内容与自动检查"
            tabIndex={0}
            onClickCapture={onReviewClickCapture}
            onDragStartCapture={onReviewDragStartCapture}
            onDragOverCapture={onReviewDragOverCapture}
            onDropCapture={onReviewDropCapture}
            onMouseMoveCapture={extendMoveSelectionThroughVisibleRange}
            className="min-w-0 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:overscroll-contain"
          >
            <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-stone-200 pb-2 text-xs text-stone-600">
              <span>
                正文着法：
                <span className="underline decoration-emerald-600 decoration-2 underline-offset-2">
                  已入谱，可点击定位
                </span>{' '}
                · <span className="bg-amber-100">待核对</span> ·{' '}
                <span className="underline decoration-dotted">计划／引用</span>
              </span>
              {sourceIndex ? (
                <label className="inline-flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={onlyPendingCommentary}
                    onChange={(event) =>
                      setOnlyPendingCommentary(event.target.checked)
                    }
                  />
                  只看待核对段落（{pendingParagraphs}）
                </label>
              ) : (
                <span>
                  {sourceError ||
                  sourceEvidence?.evidence_status === 'unavailable'
                    ? '来源对应暂不可用'
                    : '正在读取正文对应关系…'}
                </span>
              )}
            </div>
            <div className="max-w-prose space-y-2">
              {groupReviewItems(
                items.filter(
                  (item) =>
                    item.kind !== 'prose' ||
                    !onlyPendingCommentary ||
                    !sourceIndex ||
                    needsSourceReview(proseCoverage.get(item.id) ?? null),
                ),
              ).map((group) => {
                const page = group[0].evidence[0]?.page;
                const coverage = combineCoverage(
                  group.map((item) => proseCoverage.get(item.id) ?? null),
                );
                const content = group.map((item) => (
                  <ReviewItemView
                    key={item.id}
                    item={item}
                    editable={editing && !commandBusy}
                    onSelectPage={selectPage}
                    onSelectNode={selectNode}
                    onSelectAnchor={selectProseAnchor}
                    onSelectAnnotation={selectSequenceAnnotation}
                    onSelectSequenceStart={selectSequenceStart}
                    onDeleteFromHere={deleteFromHere}
                    onPromoteVariation={promoteVariation}
                    onMakeMainline={makeMainline}
                    onReattachVariation={reattachVariation}
                    onSetInitialPosition={setInitialPosition}
                    onResolveUnresolved={resolveUnresolved}
                    onSetNag={setNag}
                    onEditText={openTextEditor}
                    publishing={publishing}
                    selectedNodeIds={
                      recoveryPreview !== null && showRecoveryCandidate
                        ? new Set(
                            recoveryPreview.added_moves
                              .filter((move) => move.sequence_id === item.id)
                              .map((move) => move.node_id),
                          )
                        : moveSelection?.sequenceId === item.id
                          ? new Set(moveSelection.nodeIds)
                          : new Set()
                    }
                    onBeginMoveSelection={beginMoveSelection}
                    onExtendMoveSelection={extendMoveSelection}
                  />
                ));
                if (group.length < 3 || group[0].kind !== 'prose') {
                  return (
                    <div key={group[0].id} className="space-y-2">
                      {content}
                    </div>
                  );
                }
                return (
                  <details
                    key={group[0].id}
                    open={needsSourceReview(coverage) || undefined}
                    className="rounded border border-stone-200 bg-stone-50 px-2 py-1"
                  >
                    <summary className="cursor-pointer text-sm text-stone-600">
                      第 {page ?? '?'} 页讲解 · {group.length} 段
                      <span className="ml-2">
                        <CoverageSummary coverage={coverage} />
                      </span>
                      <span className="ml-2 text-stone-500">
                        {group[0].kind === 'prose'
                          ? group[0].text.slice(0, 70)
                          : ''}
                      </span>
                    </summary>
                    <div className="mt-2 space-y-2">{content}</div>
                  </details>
                );
              })}
            </div>
            <IssuesView
              document={document}
              acknowledgedIssueIds={acknowledgedIssueIds}
              editable={editing && !commandBusy}
              onAcknowledge={(issueId) => acknowledgeIssues([issueId])}
              onExcludeItem={excludeItem}
              onDetachPositionAnchor={detachPositionAnchor}
              onSelectPage={selectPage}
            />
          </section>
        </ReviewSourceContext.Provider>
      </div>
      <Modal
        title="预览整段变化的挂接"
        open={attachPreview !== null}
        confirmLoading={commandBusy}
        okButtonProps={{ disabled: attachInspection?.status !== 'ready' }}
        okText="保存改挂"
        cancelText="取消"
        onOk={saveAttachPreview}
        onCancel={() => setAttachPreview(null)}
      >
        {attachPreview && attachSourceNode && attachTargetSequence ? (
          <div className="space-y-3 text-sm">
            <p>
              来源：{attachSourceSequence?.title ?? '棋谱'} ·{' '}
              {moveDisplayName(attachSourceNode)}，含 {attachDescendantCount}{' '}
              个棋步及其注释。
            </p>
            <p>
              目标：{attachTargetSequence.title ?? '棋谱'} ·{' '}
              {attachTargetNode
                ? moveDisplayName(attachTargetNode)
                : '初始局面'}
            </p>
            {attachTargetNode ? (
              <div className="flex gap-2">
                <button
                  type="button"
                  aria-pressed={attachPreview.mode === 'after'}
                  onClick={() =>
                    setAttachPreview({ ...attachPreview, mode: 'after' })
                  }
                  className="rounded border px-2 py-1 aria-pressed:bg-emerald-100"
                >
                  接在此步之后
                </button>
                <button
                  type="button"
                  aria-pressed={attachPreview.mode === 'parallel'}
                  onClick={() =>
                    setAttachPreview({ ...attachPreview, mode: 'parallel' })
                  }
                  className="rounded border px-2 py-1 aria-pressed:bg-emerald-100"
                >
                  作为此步的并列变化
                </button>
              </div>
            ) : null}
            <p>起点局面：</p>
            <div className="mx-auto max-w-56">
              <Chessboard
                position={attachBoardFen}
                arePiecesDraggable={false}
              />
            </div>
            {attachInspection?.status === 'loading' ? (
              <p>正在检查新挂接…</p>
            ) : null}
            {attachInspection?.status === 'error' ? (
              <Alert type="error" title={attachInspection.message} />
            ) : null}
            {attachInspection?.status === 'ready' ? (
              <p className="text-stone-700">
                按新局面计算：剩余 {attachInspection.result.issue_count}{' '}
                个问题， 其中 {attachInspection.result.blocking_issue_count}{' '}
                个阻断问题。
              </p>
            ) : null}
          </div>
        ) : null}
      </Modal>
      <Modal
        title={`修订第 ${unresolvedEditor?.item.evidence[0]?.page ?? ''} 页待审片段`}
        open={unresolvedEditor !== null && !unresolvedEditor.pickingTarget}
        confirmLoading={commandBusy}
        okText="保存修订"
        cancelText="取消"
        onOk={() => void saveUnresolvedEditor()}
        onCancel={() => setUnresolvedEditor(null)}
        okButtonProps={{
          disabled:
            unresolvedEditor?.asKind === 'line' &&
            (unresolvedPreview?.ok !== true ||
              unresolvedPreview.uci.length === 0),
        }}
      >
        {unresolvedEditor ? (
          <div className="space-y-3 text-sm">
            <p className="rounded bg-stone-50 p-2 whitespace-pre-wrap">
              {unresolvedEditor.item.kind === 'prose'
                ? unresolvedEditor.item.text
                : (unresolvedEditor.item.raw_text ??
                  unresolvedEditor.item.details)}
            </p>
            <label className="block">
              这段内容是什么？
              <select
                className="mt-1 block w-full rounded border p-2"
                value={unresolvedEditor.asKind}
                onChange={(event) =>
                  setUnresolvedEditor({
                    ...unresolvedEditor,
                    asKind: event.target
                      .value as UnresolvedEditorState['asKind'],
                    sequenceId: '',
                    anchorNodeId: '',
                    targetNodeId: null,
                  })
                }
              >
                <option value="prose">说明或计划（不执行棋步）</option>
                <option value="annotation">挂在棋步上的注释</option>
                <option value="line">实际棋谱或变化</option>
              </select>
            </label>
            {unresolvedEditor.asKind !== 'line' ||
            unresolvedEditor.item.kind === 'prose' ? (
              <label className="block">
                {unresolvedEditor.asKind === 'line'
                  ? '仍需保留的说明（可选）'
                  : '保留的文字'}
                <Input.TextArea
                  className="mt-1"
                  rows={4}
                  value={unresolvedEditor.text}
                  onChange={(event) =>
                    setUnresolvedEditor({
                      ...unresolvedEditor,
                      text: event.target.value,
                    })
                  }
                />
              </label>
            ) : null}
            {unresolvedEditor.asKind !== 'prose' ? (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span>挂接位置：</span>
                  <span className="font-medium">
                    {unresolvedTarget
                      ? `${moveDisplayName(unresolvedTarget)} · 第 ${unresolvedTarget.evidence[0]?.page ?? '?'} 页`
                      : unresolvedSequence
                        ? '当前棋谱起点'
                        : '尚未选择'}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setUnresolvedEditor({
                        ...unresolvedEditor,
                        pickingTarget: true,
                      })
                    }
                    className="rounded border border-blue-400 bg-blue-50 px-2 py-1 text-blue-900"
                  >
                    在棋谱中点选
                  </button>
                </div>
                {unresolvedEditor.asKind === 'line' && unresolvedTarget ? (
                  <div className="flex gap-2">
                    <button
                      type="button"
                      aria-pressed={unresolvedEditor.targetMode === 'after'}
                      onClick={() =>
                        setUnresolvedEditor({
                          ...unresolvedEditor,
                          targetMode: 'after',
                        })
                      }
                      className="rounded border px-2 py-1 aria-pressed:bg-emerald-100"
                    >
                      接在这步后面
                    </button>
                    <button
                      type="button"
                      aria-pressed={unresolvedEditor.targetMode === 'parallel'}
                      onClick={() =>
                        setUnresolvedEditor({
                          ...unresolvedEditor,
                          targetMode: 'parallel',
                        })
                      }
                      className="rounded border px-2 py-1 aria-pressed:bg-emerald-100"
                    >
                      替代这步
                    </button>
                  </div>
                ) : null}
                {unresolvedEditor.asKind === 'line' ? (
                  <button
                    type="button"
                    onClick={() =>
                      setUnresolvedEditor({
                        ...unresolvedEditor,
                        sequenceId: '',
                        anchorNodeId: '',
                        targetNodeId: null,
                        targetMode: 'after',
                      })
                    }
                    className="text-stone-600 underline"
                  >
                    作为独立新棋谱
                  </button>
                ) : null}
              </div>
            ) : null}
            {unresolvedEditor.asKind === 'line' ? (
              <>
                {!unresolvedSequence ? (
                  <label className="block">
                    新棋谱的起点
                    <select
                      className="mt-1 block w-full rounded border p-2"
                      value={unresolvedEditor.initialFen}
                      onChange={(event) =>
                        setUnresolvedEditor({
                          ...unresolvedEditor,
                          initialFen: event.target.value,
                        })
                      }
                    >
                      <option value={START_FEN}>标准开局初始局面</option>
                      {items
                        .filter(
                          (item) =>
                            item.kind === 'figure' &&
                            item.position_fen_candidate !== null,
                        )
                        .map((figure) =>
                          figure.kind === 'figure' ? (
                            <option
                              key={figure.id}
                              value={figure.position_fen_candidate ?? ''}
                            >
                              第 {figure.evidence[0]?.page ?? '?'} 页图示局面
                            </option>
                          ) : null,
                        )}
                    </select>
                  </label>
                ) : null}
                <label className="block">
                  棋步（常见棋谱记法）
                  <Input.TextArea
                    className="mt-1"
                    rows={2}
                    value={unresolvedEditor.notation}
                    onChange={(event) =>
                      setUnresolvedEditor({
                        ...unresolvedEditor,
                        notation: event.target.value,
                      })
                    }
                    placeholder="例如：7...dxc4? 8.Qc2"
                  />
                </label>
                {unresolvedPreview?.ok === false ? (
                  <Alert type="warning" title={unresolvedPreview.message} />
                ) : null}
                {unresolvedPreview?.ok && unresolvedPreview.uci.length > 0 ? (
                  <div className="rounded border border-emerald-200 bg-emerald-50 p-2">
                    <p>
                      预览线路：
                      {displayReviewLine(
                        unresolvedPreview.san,
                        unresolvedPreview.nags,
                      )}
                    </p>
                    <p className="text-stone-600">
                      {unresolvedTarget
                        ? unresolvedEditor.targetMode === 'parallel'
                          ? `替代 ${moveDisplayName(unresolvedTarget)}`
                          : `接在 ${moveDisplayName(unresolvedTarget)} 后面`
                        : unresolvedSequence
                          ? '从棋谱起点接续'
                          : '新建独立棋谱'}
                    </p>
                  </div>
                ) : null}
                {followingCandidates.length > 0 ? (
                  <div className="rounded border border-blue-200 bg-blue-50 p-2">
                    <label className="flex items-start gap-2">
                      <input
                        type="checkbox"
                        checked={restoreFollowing}
                        onChange={(event) =>
                          setRestoreFollowing(event.target.checked)
                        }
                      />
                      <span>
                        同时恢复后续 {followingCandidates.length} 段连续棋步
                      </span>
                    </label>
                    <div className="mt-2 max-h-32 overflow-y-auto text-stone-700">
                      {followingCandidates.map(({ item, san, nags }) => (
                        <p key={item.id}>
                          第 {item.evidence[0]?.page ?? '?'} 页：
                          {displayReviewLine(san, nags)}
                        </p>
                      ))}
                    </div>
                    <p className="mt-1 text-xs text-stone-600">
                      只包含能按来源顺序从当前局面合法接续的片段；遇到其它内容或支线即停止。
                    </p>
                  </div>
                ) : null}
                {unresolvedBoardFen !== null ? (
                  <div className="mx-auto max-w-56">
                    <Chessboard
                      position={unresolvedBoardFen}
                      arePiecesDraggable={true}
                      onPieceDrop={addUnresolvedBoardMove}
                      onSquareClick={clickUnresolvedBoardSquare}
                    />
                    <p className="mt-1 text-center text-xs text-stone-500">
                      {unresolvedPreview?.ok
                        ? '还可在棋盘上走棋'
                        : '直接落子会替换当前无法识别的棋步文字'}
                    </p>
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        ) : null}
      </Modal>
      <Modal
        title="编辑文字"
        open={textEditor !== null}
        confirmLoading={commandBusy}
        okText="保存"
        cancelText="取消"
        onOk={saveTextEditor}
        onCancel={() => setTextEditor(null)}
      >
        <Input.TextArea
          autoSize={{ minRows: 5, maxRows: 16 }}
          value={textEditor?.text ?? ''}
          onChange={(event) =>
            setTextEditor((current) =>
              current === null
                ? null
                : { ...current, text: event.target.value },
            )
          }
        />
      </Modal>
    </div>
  );
}

function ReviewItemView({
  item,
  editable,
  onSelectPage,
  onSelectNode,
  onSelectAnchor,
  onSelectAnnotation,
  onSelectSequenceStart,
  onDeleteFromHere,
  onPromoteVariation,
  onMakeMainline,
  onReattachVariation,
  onSetInitialPosition,
  onResolveUnresolved,
  onSetNag,
  onEditText,
  publishing,
  selectedNodeIds,
  onBeginMoveSelection,
  onExtendMoveSelection,
}: {
  item: ReviewItem;
  editable: boolean;
  onSelectPage: (page: number) => void;
  onSelectNode: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onSelectAnchor: (item: ProseItem) => void;
  onSelectAnnotation: (
    sequence: AnnotatedMoveSequenceItem,
    annotation: SequenceAnnotation,
  ) => void;
  onSelectSequenceStart: (item: MoveSequenceItem) => void;
  onDeleteFromHere: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onPromoteVariation: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onMakeMainline: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onReattachVariation: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onSetInitialPosition: (sequence: MoveSequenceItem) => void;
  onResolveUnresolved: (
    item: UnresolvedReviewItem | ProseItem,
    asKind?: UnresolvedEditorState['asKind'],
  ) => void;
  onSetNag: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onEditText: (
    itemId: string,
    annotationId: string | null,
    text: string,
    textFormat: 'plain' | 'markdown' | null,
  ) => void;
  publishing: boolean;
  selectedNodeIds: Set<string>;
  onBeginMoveSelection: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onExtendMoveSelection: (sequence: MoveSequenceItem, node: MoveNode) => void;
}) {
  const { index: sourceIndex } = useReviewSource();
  switch (item.kind) {
    case 'heading': {
      const tag = HEADING_TAGS[Math.min(5, Math.max(0, item.level - 1))];
      const Heading = tag;
      return (
        <Heading className="mt-4 mb-2 font-semibold text-stone-900">
          {item.text}
          <EvidencePages evidence={item.evidence} onSelectPage={onSelectPage} />
          {editable ? (
            <EditTextButton
              onClick={() => onEditText(item.id, null, item.text, null)}
            />
          ) : null}
        </Heading>
      );
    }
    case 'prose': {
      const coverage = paragraphCoverage(item.text, item.evidence, sourceIndex);
      return (
        <article data-source-item-id={item.id}>
          <div className="text-stone-800">
            <ReviewSourceText
              text={item.text}
              textFormat={item.text_format}
              coverage={coverage}
            />
          </div>
          <CoverageSummary coverage={coverage} />
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
            {editable ? (
              <>
                <button
                  type="button"
                  onClick={() => onResolveUnresolved(item, 'line')}
                  className="rounded border border-emerald-500 bg-white px-2 py-0.5 text-xs"
                >
                  转为棋步
                </button>
                <EditTextButton
                  onClick={() =>
                    onEditText(
                      item.id,
                      null,
                      item.text,
                      item.text_format ?? 'plain',
                    )
                  }
                />
              </>
            ) : null}
          </span>
        </article>
      );
    }
    case 'move_sequence': {
      return (
        <MoveSequenceView
          item={item}
          editable={editable}
          onSelectPage={onSelectPage}
          onSelectNode={onSelectNode}
          onSelectAnnotation={onSelectAnnotation}
          onSelectStart={onSelectSequenceStart}
          onDeleteFromHere={onDeleteFromHere}
          onPromoteVariation={onPromoteVariation}
          onMakeMainline={onMakeMainline}
          onReattachVariation={onReattachVariation}
          onSetInitialPosition={onSetInitialPosition}
          onSetNag={onSetNag}
          onEditText={onEditText}
          publishing={publishing}
          selectedNodeIds={selectedNodeIds}
          onBeginMoveSelection={onBeginMoveSelection}
          onExtendMoveSelection={onExtendMoveSelection}
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
          {editable ? (
            <div className="mt-2 flex gap-2">
              {item.raw_text ? (
                <button
                  type="button"
                  onClick={() => onResolveUnresolved(item, 'line')}
                  className="rounded border border-red-500 bg-white px-2 py-1 text-sm"
                >
                  转为棋步
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => onResolveUnresolved(item)}
                className="rounded border border-stone-300 bg-white px-2 py-1 text-sm"
              >
                修订此片段
              </button>
            </div>
          ) : null}
        </div>
      );
    }
  }
}

function MoveSequenceView({
  item,
  editable,
  onSelectPage,
  onSelectNode,
  onSelectAnnotation,
  onSelectStart,
  onDeleteFromHere,
  onPromoteVariation,
  onMakeMainline,
  onReattachVariation,
  onSetInitialPosition,
  onSetNag,
  onEditText,
  publishing,
  selectedNodeIds,
  onBeginMoveSelection,
  onExtendMoveSelection,
}: {
  item: MoveSequenceItem;
  editable: boolean;
  onSelectPage: (page: number) => void;
  onSelectNode: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onSelectAnnotation: (
    sequence: AnnotatedMoveSequenceItem,
    annotation: SequenceAnnotation,
  ) => void;
  onSelectStart: (item: MoveSequenceItem) => void;
  onDeleteFromHere: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onPromoteVariation: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onMakeMainline: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onReattachVariation: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onSetInitialPosition: (sequence: MoveSequenceItem) => void;

  onSetNag: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onEditText: (
    itemId: string,
    annotationId: string | null,
    text: string,
    textFormat: 'plain' | 'markdown' | null,
  ) => void;
  publishing: boolean;
  selectedNodeIds: Set<string>;
  onBeginMoveSelection: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onExtendMoveSelection: (sequence: MoveSequenceItem, node: MoveNode) => void;
}) {
  const blocks = useMemo<CompactReviewBlock[]>(() => {
    let readingBlocks: ReviewReadingBlock[];
    if (isAnnotatedMoveSequence(item)) {
      readingBlocks = buildReviewReadingFlow(item);
    } else {
      readingBlocks = buildReviewMoveRows(item.nodes).map((row) => ({
        kind: 'move_row' as const,
        key: `move:${row.key}`,
        row,
      }));
    }
    return compactReviewBlocks(readingBlocks);
  }, [item]);
  const { index: sourceIndex, onlyPending } = useReviewSource();
  const displayBlocks = useMemo(
    () =>
      groupReviewAnnotations(
        blocks.filter(
          (block) =>
            block.kind !== 'annotation' ||
            !onlyPending ||
            !sourceIndex ||
            needsSourceReview(
              paragraphCoverage(
                block.annotation.text,
                block.annotation.evidence,
                sourceIndex,
              ),
            ),
        ),
      ),
    [blocks, onlyPending, sourceIndex],
  );
  const [contextMenu, setContextMenu] = useState<ReviewContextMenuState | null>(
    null,
  );

  function openContextMenu(
    event: ReactMouseEvent,
    title: string,
    evidence: EvidenceRef[],
    actions: ContextMenuAction[],
  ) {
    event.preventDefault();
    event.stopPropagation();
    const pages = uniqueEvidencePages(evidence);
    if (pages[0] !== undefined) onSelectPage(pages[0]);
    const width = 224;
    const estimatedHeight = 76 + (pages.length + actions.length) * 34;
    setContextMenu({
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8)),
      y: Math.max(
        8,
        Math.min(event.clientY, window.innerHeight - estimatedHeight - 8),
      ),
      title,
      pages,
      actions,
    });
  }

  function openMoveContextMenu(event: ReactMouseEvent, node: MoveNode) {
    const actions: ContextMenuAction[] = [];
    if (editable) {
      actions.push(
        {
          key: 'promote',
          label: '提升变招',
          disabled: node.sibling_order === 0,
          onSelect: () => onPromoteVariation(item, node),
        },
        {
          key: 'mainline',
          label: '设为主线',
          disabled: isNodeOnMainline(item, node),
          onSelect: () => onMakeMainline(item, node),
        },
        {
          key: 'reattach',
          label: '重新挂接分支',
          onSelect: () => onReattachVariation(item, node),
        },
        {
          key: 'nag',
          label: '设置评价',
          onSelect: () => onSetNag(item, node),
        },
        {
          key: 'delete',
          label: '从此处开始删除',
          danger: true,
          onSelect: () => onDeleteFromHere(item, node),
        },
      );
    }
    openContextMenu(event, moveDisplayName(node), node.evidence, actions);
  }

  function openAnnotationContextMenu(
    event: ReactMouseEvent,
    annotation: SequenceAnnotation,
  ) {
    const actions: ContextMenuAction[] = [];
    if (annotation.anchor !== null && isAnnotatedMoveSequence(item)) {
      actions.push({
        key: 'locate',
        label: '定位注释局面',
        onSelect: () => onSelectAnnotation(item, annotation),
      });
    }
    if (editable) {
      actions.push({
        key: 'edit',
        label: '编辑注释',
        onSelect: () =>
          onEditText(
            item.id,
            annotation.id,
            annotation.text,
            annotation.text_format ?? 'plain',
          ),
      });
    }
    openContextMenu(event, '谱内注释', annotation.evidence, actions);
  }

  return (
    <section className="overflow-hidden border-y border-stone-200 bg-white">
      <header className="flex flex-wrap items-center gap-2 border-b border-stone-200 px-2 py-1.5">
        <h3 className="font-semibold text-stone-900">{item.title ?? '棋谱'}</h3>
        <button
          type="button"
          onClick={() => onSelectStart(item)}
          data-review-sequence-start={item.id}
          className="rounded px-2 py-0.5 text-xs text-stone-600 hover:bg-stone-100"
        >
          回到初始局面
        </button>
        {editable ? (
          <button
            type="button"
            onClick={() => onSetInitialPosition(item)}
            className="rounded px-2 py-0.5 text-xs text-amber-800 hover:bg-amber-50"
          >
            修正初始 FEN
          </button>
        ) : null}
      </header>
      <div>
        {displayBlocks.map((block) => {
          if (block.kind === 'annotation_group') {
            const coverage = combineCoverage(
              block.blocks.map((part) =>
                paragraphCoverage(
                  part.annotation.text,
                  part.annotation.evidence,
                  sourceIndex,
                ),
              ),
            );
            return (
              <details
                key={block.key}
                open={needsSourceReview(coverage) || undefined}
                className="border-b border-stone-100 px-2 py-1"
              >
                <summary className="cursor-pointer text-sm text-stone-600">
                  讲解 · {block.blocks.length} 段
                  <span className="ml-2">
                    <CoverageSummary coverage={coverage} />
                  </span>
                  <span className="ml-2 text-stone-500">
                    {block.blocks[0].annotation.text.slice(0, 65)}
                  </span>
                </summary>
                <div className="mt-1">
                  {block.blocks.map((part) => (
                    <SequenceAnnotationView
                      key={part.key}
                      annotation={part.annotation}
                      variationDepth={part.variationDepth}
                      variationPresentation={part.variationPresentation}
                      onSelectAnchor={() => {
                        if (isAnnotatedMoveSequence(item)) {
                          onSelectAnnotation(item, part.annotation);
                        }
                      }}
                      onContextMenu={(event) =>
                        openAnnotationContextMenu(event, part.annotation)
                      }
                    />
                  ))}
                </div>
              </details>
            );
          }
          if (block.kind === 'mainline_row') {
            return (
              <MainlineMoveRow
                key={block.key}
                sequence={item}
                row={block.row}
                onSelectNode={onSelectNode}
                onContextMenu={openMoveContextMenu}
                publishing={publishing}
                selectedNodeIds={selectedNodeIds}
                onBeginMoveSelection={onBeginMoveSelection}
                onExtendMoveSelection={onExtendMoveSelection}
              />
            );
          }
          if (block.kind === 'variation_line') {
            return (
              <VariationLine
                key={block.key}
                sequence={item}
                block={block}
                onSelectNode={onSelectNode}
                onContextMenu={openMoveContextMenu}
                publishing={publishing}
                selectedNodeIds={selectedNodeIds}
                onBeginMoveSelection={onBeginMoveSelection}
                onExtendMoveSelection={onExtendMoveSelection}
              />
            );
          }
          return (
            <SequenceAnnotationView
              key={block.key}
              annotation={block.annotation}
              variationDepth={block.variationDepth}
              variationPresentation={block.variationPresentation}
              onSelectAnchor={() => {
                if (isAnnotatedMoveSequence(item)) {
                  onSelectAnnotation(item, block.annotation);
                }
              }}
              onContextMenu={(event) =>
                openAnnotationContextMenu(event, block.annotation)
              }
            />
          );
        })}
      </div>
      <ReviewContextMenu
        menu={contextMenu}
        onSelectPage={onSelectPage}
        onClose={() => setContextMenu(null)}
      />
    </section>
  );
}

function SequenceAnnotationView({
  annotation,
  variationDepth,
  variationPresentation,
  onSelectAnchor,
  onContextMenu,
}: {
  annotation: SequenceAnnotation;
  variationDepth: number;
  variationPresentation: 'mainline' | 'parenthetical' | 'rail';
  onSelectAnchor: () => void;
  onContextMenu: (event: ReactMouseEvent) => void;
}) {
  const { index: sourceIndex } = useReviewSource();
  const coverage = paragraphCoverage(
    annotation.text,
    annotation.evidence,
    sourceIndex,
  );
  const visualDepth = Math.min(5, variationDepth);
  if (/^[\d\s.()[\]…,:;!?–-]+$/.test(annotation.text.trim())) return null;
  const content = (
    <ReviewSourceText
      text={annotation.text}
      textFormat={annotation.text_format}
      coverage={coverage}
    />
  );
  const compactContent =
    annotation.text.length > 110 ? (
      <details
        className="min-w-0"
        open={needsSourceReview(coverage) || undefined}
      >
        <summary className="cursor-pointer truncate text-stone-500">
          {annotation.text.slice(0, 95)}…
        </summary>
        <div className="mt-1">{content}</div>
      </details>
    ) : (
      content
    );
  return (
    <div
      data-annotation-id={annotation.id}
      data-variation-depth={variationDepth}
      style={
        variationPresentation === 'rail'
          ? { paddingLeft: `${visualDepth * 14 + 8}px` }
          : undefined
      }
      onContextMenu={onContextMenu}
      className={`relative py-1 pr-2 text-sm leading-5 text-stone-700 ${
        variationPresentation === 'mainline'
          ? 'border-b border-stone-100 pl-9'
          : variationPresentation === 'parenthetical'
            ? 'pl-3 text-stone-500'
            : ''
      }`}
    >
      {variationPresentation === 'rail' ? (
        <BranchRails depth={visualDepth} />
      ) : null}
      <div className="flex items-baseline gap-1">
        {variationPresentation === 'parenthetical' ? (
          <span aria-hidden="true">(</span>
        ) : null}
        {annotation.anchor !== null ? (
          <div
            role="button"
            tabIndex={0}
            onClick={onSelectAnchor}
            onKeyDown={(event) => {
              if (
                event.target === event.currentTarget &&
                (event.key === 'Enter' || event.key === ' ')
              ) {
                event.preventDefault();
                onSelectAnchor();
              }
            }}
            className="block min-w-0 flex-1 text-left italic hover:text-stone-950"
          >
            <CoverageSummary coverage={coverage} />
            {compactContent}
          </div>
        ) : (
          <div className="min-w-0 flex-1 italic">
            <CoverageSummary coverage={coverage} />
            {compactContent}
          </div>
        )}
        {variationPresentation === 'parenthetical' ? (
          <span aria-hidden="true">)</span>
        ) : null}
      </div>
    </div>
  );
}

function MainlineMoveRow({
  sequence,
  row,
  onSelectNode,
  onContextMenu,
  publishing,
  selectedNodeIds,
  onBeginMoveSelection,
  onExtendMoveSelection,
}: {
  sequence: MoveSequenceItem;
  row: ReviewMoveRow;
  onSelectNode: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onContextMenu: (event: ReactMouseEvent, node: MoveNode) => void;
  publishing: boolean;
  selectedNodeIds: Set<string>;
  onBeginMoveSelection: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onExtendMoveSelection: (sequence: MoveSequenceItem, node: MoveNode) => void;
}) {
  return (
    <div
      data-variation-depth={row.variationDepth}
      className="grid min-h-8 grid-cols-[2.25rem_1fr_1fr] items-stretch border-b border-stone-100 last:border-b-0"
    >
      <span className="flex items-center justify-center bg-stone-50 font-mono text-xs text-stone-400">
        {mainlineGutter(row)}
      </span>
      {row.fallback !== null ? (
        <div className="col-span-2 min-w-0">
          <MoveCell
            sequence={sequence}
            node={row.fallback}
            onSelectNode={onSelectNode}
            onContextMenu={onContextMenu}
            publishing={publishing}
            selected={selectedNodeIds.has(row.fallback.id)}
            onBeginMoveSelection={onBeginMoveSelection}
            onExtendMoveSelection={onExtendMoveSelection}
            fullWidth
          />
        </div>
      ) : (
        <>
          <div className="min-w-0 border-l border-stone-100">
            {row.white !== null ? (
              <MoveCell
                sequence={sequence}
                node={row.white}
                onSelectNode={onSelectNode}
                onContextMenu={onContextMenu}
                publishing={publishing}
                selected={selectedNodeIds.has(row.white.id)}
                onBeginMoveSelection={onBeginMoveSelection}
                onExtendMoveSelection={onExtendMoveSelection}
                fullWidth
              />
            ) : null}
          </div>
          <div className="min-w-0 border-l border-stone-100">
            {row.black !== null ? (
              <MoveCell
                sequence={sequence}
                node={row.black}
                onSelectNode={onSelectNode}
                onContextMenu={onContextMenu}
                publishing={publishing}
                selected={selectedNodeIds.has(row.black.id)}
                onBeginMoveSelection={onBeginMoveSelection}
                onExtendMoveSelection={onExtendMoveSelection}
                fullWidth
              />
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}

function VariationLine({
  sequence,
  block,
  onSelectNode,
  onContextMenu,
  publishing,
  selectedNodeIds,
  onBeginMoveSelection,
  onExtendMoveSelection,
}: {
  sequence: MoveSequenceItem;
  block: Extract<CompactReviewBlock, { kind: 'variation_line' }>;
  onSelectNode: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onContextMenu: (event: ReactMouseEvent, node: MoveNode) => void;
  publishing: boolean;
  selectedNodeIds: Set<string>;
  onBeginMoveSelection: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onExtendMoveSelection: (sequence: MoveSequenceItem, node: MoveNode) => void;
}) {
  const visualDepth = Math.min(5, block.variationDepth);
  const parenthetical = block.presentation === 'parenthetical';
  return (
    <div
      data-variation-depth={block.variationDepth}
      data-variation-path={block.variationPath.join('/')}
      data-variation-presentation={block.presentation}
      style={
        parenthetical ? undefined : { paddingLeft: `${visualDepth * 14 + 8}px` }
      }
      className={`relative py-1 pr-2 text-sm leading-6 ${
        parenthetical ? 'pl-3 italic text-stone-500' : ''
      }`}
    >
      {!parenthetical ? <BranchRails depth={visualDepth} /> : null}
      <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0">
        {parenthetical ? <span aria-hidden="true">(</span> : null}
        {block.rows.map((row) => (
          <span key={row.key} className="inline-flex items-baseline gap-1">
            {row.moveNumber !== null ? (
              <span className="font-mono text-xs text-stone-400">
                {variationGutter(row)}
              </span>
            ) : null}
            {row.fallback !== null ? (
              <MoveCell
                sequence={sequence}
                node={row.fallback}
                onSelectNode={onSelectNode}
                onContextMenu={onContextMenu}
                publishing={publishing}
                selected={selectedNodeIds.has(row.fallback.id)}
                onBeginMoveSelection={onBeginMoveSelection}
                onExtendMoveSelection={onExtendMoveSelection}
              />
            ) : (
              <>
                {row.white !== null ? (
                  <MoveCell
                    sequence={sequence}
                    node={row.white}
                    onSelectNode={onSelectNode}
                    onContextMenu={onContextMenu}
                    publishing={publishing}
                    selected={selectedNodeIds.has(row.white.id)}
                    onBeginMoveSelection={onBeginMoveSelection}
                    onExtendMoveSelection={onExtendMoveSelection}
                  />
                ) : null}
                {row.black !== null ? (
                  <MoveCell
                    sequence={sequence}
                    node={row.black}
                    onSelectNode={onSelectNode}
                    onContextMenu={onContextMenu}
                    publishing={publishing}
                    selected={selectedNodeIds.has(row.black.id)}
                    onBeginMoveSelection={onBeginMoveSelection}
                    onExtendMoveSelection={onExtendMoveSelection}
                  />
                ) : null}
              </>
            )}
          </span>
        ))}
        {parenthetical ? <span aria-hidden="true">)</span> : null}
      </div>
    </div>
  );
}

function BranchRails({ depth }: { depth: number }) {
  if (depth === 0) return null;
  return (
    <span aria-hidden="true">
      {Array.from({ length: depth }, (_, index) => (
        <span
          key={index}
          data-branch-rail={index + 1}
          style={{ left: `${index * 14}px` }}
          className="absolute inset-y-0 border-l-2 border-stone-300"
        />
      ))}
      <span
        style={{ left: `${(depth - 1) * 14}px` }}
        className="absolute top-3 w-3 border-t-2 border-stone-300"
      />
    </span>
  );
}

function reviewNodeDisplay(node: MoveNode) {
  const isValid = node.validation_status === 'valid';
  const source = isValid
    ? (node.san_candidate ?? node.move_text)
    : node.move_text;
  const overridden = node.extensions?.['chess-workbench.nag-override'] === true;
  const san = overridden && !isValid ? formatMoveNotation(source).move : source;
  const nags =
    (node.nags?.length ?? 0) > 0 || overridden
      ? (node.nags ?? [])
      : formatMoveNotation(node.move_text).annotations.map(({ code }) => code);
  return { san, nags };
}

function MoveCell({
  sequence,
  node,
  onSelectNode,
  onContextMenu,
  publishing,
  selected,
  onBeginMoveSelection,
  onExtendMoveSelection,
  fullWidth = false,
}: {
  sequence: MoveSequenceItem;
  node: MoveNode;
  onSelectNode: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onContextMenu: (event: ReactMouseEvent, node: MoveNode) => void;
  publishing: boolean;
  selected: boolean;
  onBeginMoveSelection: (sequence: MoveSequenceItem, node: MoveNode) => void;
  onExtendMoveSelection: (sequence: MoveSequenceItem, node: MoveNode) => void;
  fullWidth?: boolean;
}) {
  const { focused } = useReviewSource();
  const sourceLinked =
    focused?.sequenceId === sequence.id && focused.nodeId === node.id;
  const isNavigable =
    node.validation_status === 'valid' && node.fen_after !== null;
  const validationClass = moveValidationClass(node.validation_status);
  const { san, nags } = reviewNodeDisplay(node);
  const displayName = formatMoveNotation(san, nags).move;
  const content = <MoveNotation san={san} nags={nags} />;
  return isNavigable ? (
    <button
      type="button"
      aria-label={displayName}
      draggable={!publishing}
      data-review-sequence-id={sequence.id}
      data-review-node-id={node.id}
      data-validation-status={node.validation_status}
      data-source-linked={sourceLinked || undefined}
      data-publication-selected={selected || undefined}
      onClick={() => {
        if (!publishing) onSelectNode(sequence, node);
      }}
      onMouseDown={(event) => {
        if (publishing && event.button === 0) {
          event.preventDefault();
          onBeginMoveSelection(sequence, node);
        }
      }}
      onMouseEnter={() => onExtendMoveSelection(sequence, node)}
      onContextMenu={(event) => onContextMenu(event, node)}
      className={`${fullWidth ? 'flex h-full w-full' : 'inline-flex'} min-w-0 select-none items-center rounded-sm px-1.5 py-0.5 text-left text-sm leading-5 hover:bg-emerald-100 ${selected ? 'bg-emerald-200 ring-1 ring-inset ring-emerald-700' : validationClass} ${sourceLinked ? 'bg-sky-100 ring-2 ring-sky-600' : ''}`}
    >
      {content}
    </button>
  ) : (
    <span
      aria-disabled="true"
      tabIndex={0}
      draggable={!publishing}
      data-review-sequence-id={sequence.id}
      data-review-node-id={node.id}
      data-validation-status={node.validation_status}
      data-publication-selected={selected || undefined}
      onMouseDown={(event) => {
        if (publishing && event.button === 0) {
          event.preventDefault();
          onBeginMoveSelection(sequence, node);
        }
      }}
      onMouseEnter={() => onExtendMoveSelection(sequence, node)}
      onContextMenu={(event) => onContextMenu(event, node)}
      className={`${fullWidth ? 'flex h-full w-full' : 'inline-flex'} min-w-0 select-none items-center rounded-sm px-1.5 py-0.5 text-sm leading-5 ${selected ? 'bg-emerald-200 ring-1 ring-inset ring-emerald-700' : validationClass}`}
    >
      {content}
    </span>
  );
}

function ReviewContextMenu({
  menu,
  onSelectPage,
  onClose,
}: {
  menu: ReviewContextMenuState | null;
  onSelectPage: (page: number) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    if (menu === null) return;
    const close = () => onClose();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('click', close);
    window.addEventListener('resize', close);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('click', close);
      window.removeEventListener('resize', close);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [menu, onClose]);

  if (menu === null) return null;
  return (
    <div
      role="menu"
      aria-label={`${menu.title} 操作菜单`}
      style={{ left: menu.x, top: menu.y }}
      onClick={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.preventDefault()}
      className="fixed z-50 w-56 overflow-hidden rounded-md border border-stone-300 bg-white py-1 text-sm shadow-xl"
    >
      <p className="truncate border-b border-stone-100 px-3 py-1.5 font-semibold text-stone-800">
        {menu.title}
      </p>
      {menu.pages.length > 0 ? (
        menu.pages.map((page) => (
          <button
            key={page}
            type="button"
            role="menuitem"
            onClick={() => {
              onSelectPage(page);
              onClose();
            }}
            className="block w-full px-3 py-1.5 text-left text-stone-600 hover:bg-stone-100"
          >
            来源：第 {page} 页
          </button>
        ))
      ) : (
        <p className="px-3 py-1.5 text-stone-400">无来源页</p>
      )}
      {menu.actions.length > 0 ? (
        <div className="border-t border-stone-100 pt-1">
          {menu.actions.map((action) => (
            <button
              key={action.key}
              type="button"
              role="menuitem"
              disabled={action.disabled}
              onClick={() => {
                action.onSelect();
                onClose();
              }}
              className={`block w-full px-3 py-1.5 text-left hover:bg-stone-100 disabled:cursor-not-allowed disabled:opacity-35 ${
                action.danger
                  ? 'text-red-700 hover:bg-red-50'
                  : 'text-stone-800'
              }`}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function mainlineGutter(row: ReviewMoveRow): string {
  if (row.fallback !== null || row.moveNumber === null) return '';
  return row.white === null ? `${row.moveNumber}...` : String(row.moveNumber);
}

function variationGutter(row: ReviewMoveRow): string {
  if (row.moveNumber === null) return '';
  return row.white === null ? `${row.moveNumber}...` : `${row.moveNumber}.`;
}

function moveDisplayName(node: MoveNode): string {
  const { moveNumber, side } = reviewMoveTurn(node);
  const { san, nags } = reviewNodeDisplay(node);
  const name = moveNotationText(san, nags);
  if (moveNumber === null || side === null) {
    return name;
  }
  const prefix = side === 'w' ? `${moveNumber}.` : `${moveNumber}...`;
  return `${prefix} ${name}`;
}

function moveValidationClass(status: MoveNode['validation_status']): string {
  if (status === 'invalid') return 'bg-red-100 text-red-800';
  if (status === 'ambiguous') return 'bg-amber-100 text-amber-900';
  if (status === 'unvalidated') return 'bg-stone-200 text-stone-600';
  return 'text-stone-800';
}

function displayReviewLine(san: string[], nags: (number | null)[]): string {
  return san
    .map((move, index) => {
      const nag = nags[index];
      return moveNotationText(
        move,
        nag === null || nag === undefined ? [] : [nag],
      );
    })
    .join(' ');
}

function isNodeOnMainline(
  sequence: MoveSequenceItem,
  selected: MoveNode,
): boolean {
  let node: MoveNode | undefined = selected;
  while (node !== undefined) {
    if (node.sibling_order > 0) return false;
    node =
      node.parent_id === null
        ? undefined
        : sequence.nodes.find((candidate) => candidate.id === node?.parent_id);
  }
  return true;
}

function EditTextButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="ml-1 rounded border border-stone-300 bg-white px-2 py-0.5 text-xs font-normal"
    >
      编辑文字
    </button>
  );
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
  acknowledgedIssueIds,
  editable,
  onAcknowledge,
  onExcludeItem,
  onDetachPositionAnchor,
  onSelectPage,
}: {
  document: PdfReviewDocument;
  acknowledgedIssueIds: Set<string>;
  editable: boolean;
  onAcknowledge: (issueId: string) => void;
  onExcludeItem: (itemId: string) => void;
  onDetachPositionAnchor: (issueId: string) => void;
  onSelectPage: (page: number) => void;
}) {
  const { inspection } = document;
  const excludableItemIds = new Set(
    (document.package.items ?? [])
      .filter((item) => item.kind !== 'move_sequence')
      .map((item) => item.id),
  );
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
          {inspection.issues.map((issue) => {
            const canDetachPositionAnchor =
              issue.blocking &&
              (issue.scope === 'item' || issue.scope === 'annotation') &&
              (issue.code === 'position_anchor_no_match' ||
                issue.code === 'position_anchor_ambiguous');
            return (
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
                {!issue.blocking ? (
                  acknowledgedIssueIds.has(issue.issue_id) ? (
                    <Tag color="green">已确认</Tag>
                  ) : editable ? (
                    <button
                      type="button"
                      onClick={() => onAcknowledge(issue.issue_id)}
                      className="ml-2 rounded border border-stone-300 bg-white px-2 py-0.5 text-xs"
                    >
                      确认此警告
                    </button>
                  ) : null
                ) : editable && canDetachPositionAnchor ? (
                  <button
                    type="button"
                    onClick={() => onDetachPositionAnchor(issue.issue_id)}
                    className="ml-2 rounded border border-amber-400 bg-white px-2 py-0.5 text-xs text-amber-800"
                  >
                    保留文字并取消局面关联
                  </button>
                ) : editable &&
                  issue.item_id !== null &&
                  issue.node_id === null &&
                  excludableItemIds.has(issue.item_id) ? (
                  <button
                    type="button"
                    onClick={() => onExcludeItem(issue.item_id!)}
                    className="ml-2 rounded border border-red-300 bg-white px-2 py-0.5 text-xs text-red-700"
                  >
                    排除此内容
                  </button>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
