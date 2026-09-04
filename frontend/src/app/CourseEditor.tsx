import {
  Alert,
  Button,
  Card,
  Divider,
  Dropdown,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { Chess } from 'chess.js';
import {
  type DragEvent as ReactDragEvent,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react';
import { Chessboard } from 'react-chessboard';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import useSWR from 'swr';

import { fetchJson, requestJson } from '../logic/api/client';
import type {
  AnalysisCacheLookup,
  EngineParameters,
} from '../logic/api/engineTypes';
import type {
  Course,
  CitableSource,
  ContentHistory,
  CourseModule,
  ModuleEditor,
  Occurrence,
  PdfAssetListResponse,
  PdfExtractionDocumentListResponse,
  PdfExtractionListResponse,
} from '../logic/api/types';
import {
  FAST_MOVE_ANIMATION_MS,
  lichessSquareStyles,
} from './boardInteraction';
import {
  CourseEnginePanel,
  type CourseEngineArrow,
  type CourseSectionAnalysisProgress,
} from './CourseEnginePanel';
import {
  CourseScore,
  CourseScoreControls,
  type CourseMoveAction,
} from './CourseScore';
import { createDraftState, editorDraftReducer } from './editorDraft';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

export function CourseEditor() {
  const { courseId = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const {
    data: course,
    error: courseError,
    mutate: mutateCourse,
  } = useSWR<Course>(courseId ? `/api/courses/${courseId}` : null, fetchJson);
  const { data: modules = [], mutate: mutateModules } = useSWR<CourseModule[]>(
    courseId ? `/api/courses/${courseId}/modules` : null,
    fetchJson,
  );
  const [moduleId, setModuleId] = useState<string>();
  const [occurrenceId, setOccurrenceId] = useState<string>();
  const [pendingFen, setPendingFen] = useState<string>();
  const [recordBoardMoves, setRecordBoardMoves] = useState(true);
  const [boardOrientation, setBoardOrientation] = useState<'white' | 'black'>(
    'white',
  );
  const [selectedSquare, setSelectedSquare] = useState<string>();
  const [engineArrows, setEngineArrows] = useState<CourseEngineArrow[]>([]);
  const [sectionAnalysisProgress, setSectionAnalysisProgress] =
    useState<CourseSectionAnalysisProgress>();
  const sectionAnalysisController = useRef<AbortController>();
  const [moduleModal, setModuleModal] = useState(false);
  const [publishModal, setPublishModal] = useState(false);
  const [publishTarget, setPublishTarget] = useState<string>();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [readingMode, setReadingMode] = useState(true);
  const [leftPaneMode, setLeftPaneMode] = useState<'chapters' | 'source'>(
    'chapters',
  );
  const [activeSourceSpanId, setActiveSourceSpanId] = useState<string>();
  const [expandedModuleIds, setExpandedModuleIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [reorderingModules, setReorderingModules] = useState(false);
  const [narrativeModal, setNarrativeModal] = useState(false);
  const [narrativeMarkdown, setNarrativeMarkdown] = useState('');
  const [narrativeSourceSpanIds, setNarrativeSourceSpanIds] = useState<
    string[]
  >([]);
  const [contextNoteId, setContextNoteId] = useState<string>();
  const [importModal, setImportModal] = useState(false);
  const [importText, setImportText] = useState('');
  const [importSourceTitle, setImportSourceTitle] = useState('');
  const [importKey, setImportKey] = useState('');
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string>();
  const [baseline, setBaseline] = useState({
    markdown: '',
    sourceSpanIds: [] as string[],
  });
  const [draft, dispatchDraft] = useReducer(
    editorDraftReducer,
    createDraftState({ markdown: '', sourceSpanIds: [] }),
  );
  const [form] = Form.useForm();
  const { data: citableSources = [] } = useSWR<CitableSource[]>(
    '/api/citable-sources',
    fetchJson,
  );
  const { data: explorerCourses = [] } = useSWR<Course[]>(
    publishModal ? '/api/courses?mode=opening_explorer&sort=title_asc' : null,
    fetchJson,
  );

  useEffect(() => {
    if (!moduleId && modules[0]) {
      const requested = searchParams.get('module');
      setModuleId(
        modules.find((item) => item.id === requested)?.id ??
          modules.find((item) => item.parent_id === null)?.id ??
          modules[0].id,
      );
    }
  }, [moduleId, modules, searchParams]);
  useEffect(() => {
    setExpandedModuleIds((current) => {
      const next = new Set(current);
      let changed = false;
      for (const item of modules) {
        if (item.parent_id === null && !next.has(item.id)) {
          next.add(item.id);
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [modules]);
  const editorKey =
    course?.mode !== 'opening_explorer' && courseId && moduleId
      ? `/api/courses/${courseId}/editor/${moduleId}`
      : null;
  const {
    data: moduleEditor,
    error: moduleEditorError,
    mutate: mutateModuleEditor,
  } = useSWR<ModuleEditor>(editorKey, fetchJson);
  const explorerEditorKey =
    course?.mode === 'opening_explorer' && modules.length
      ? `explorer-editors:${courseId}:${modules.map((item) => item.id).join(',')}`
      : null;
  const {
    data: explorerEditors,
    error: explorerEditorError,
    mutate: mutateExplorerEditors,
  } = useSWR<ModuleEditor[]>(explorerEditorKey, () =>
    Promise.all(
      modules.map((item) =>
        fetchJson<ModuleEditor>(`/api/courses/${courseId}/editor/${item.id}`),
      ),
    ),
  );
  const editor = useMemo(() => {
    if (course?.mode !== 'opening_explorer') return moduleEditor;
    const active =
      explorerEditors?.find((item) => item.module.id === moduleId) ??
      explorerEditors?.[0];
    if (!active || !explorerEditors) return undefined;
    return {
      ...active,
      content_blocks: [],
      occurrences: explorerEditors.flatMap((item) => item.occurrences),
      notes: explorerEditors.flatMap((item) => item.notes),
    };
  }, [course?.mode, explorerEditors, moduleEditor, moduleId]);
  const scoreRootId = useMemo(
    () =>
      editor?.content_blocks.find(
        (block) => block.kind === 'move_sequence' && block.root_occurrence_id,
      )?.root_occurrence_id ??
      editor?.occurrences.find((item) => item.parent_id === null)?.id,
    [editor],
  );
  const courseSourceSpanIds = useMemo(() => {
    const ids = new Set<string>();
    for (const block of editor?.content_blocks ?? []) {
      for (const id of block.source_span_ids ?? []) ids.add(id);
    }
    for (const note of editor?.notes ?? []) {
      for (const id of note.rendered_source_span_ids) ids.add(id);
    }
    for (const occurrence of editor?.occurrences ?? []) {
      const sourceSpanIds = occurrence.context?.source_span_ids;
      if (!Array.isArray(sourceSpanIds)) continue;
      for (const id of sourceSpanIds) {
        if (typeof id === 'string') ids.add(id);
      }
    }
    return ids;
  }, [editor]);
  const hasPdfPageSources = citableSources.some(
    (item) =>
      courseSourceSpanIds.has(item.source_span.id) &&
      item.source_span.locator.kind === 'page' &&
      item.source_span.source_file_id !== null,
  );
  const { data: pdfAssets } = useSWR<PdfAssetListResponse>(
    hasPdfPageSources ? '/api/pdf-assets' : null,
    fetchJson,
  );
  const { data: pdfExtractions } = useSWR<PdfExtractionListResponse>(
    hasPdfPageSources ? '/api/pdf-extractions' : null,
    fetchJson,
  );
  const { data: pdfDocuments } = useSWR<PdfExtractionDocumentListResponse>(
    hasPdfPageSources ? '/api/pdf-extraction-documents' : null,
    fetchJson,
  );
  const editorError = moduleEditorError ?? explorerEditorError;
  useEffect(() => {
    const requested = searchParams.get('occurrence');
    const root =
      editor?.occurrences.find((item) => item.id === requested) ??
      editor?.occurrences.find(
        (item) => item.module_id === moduleId && item.parent_id === null,
      ) ??
      editor?.occurrences.find((item) => item.parent_id === null);
    if (
      editor &&
      root &&
      !editor.occurrences.some((item) => item.id === occurrenceId)
    ) {
      setOccurrenceId(root.id);
      setPendingFen(undefined);
    }
  }, [editor, moduleId, occurrenceId, searchParams]);

  const byId = useMemo(
    () => new Map(editor?.occurrences.map((item) => [item.id, item]) ?? []),
    [editor],
  );
  const scoreOccurrences = useMemo(() => {
    if (!editor || course?.mode !== 'opening_explorer') {
      return editor?.occurrences ?? [];
    }
    const canonicalByPosition = new Map<string, string>();
    for (const occurrence of editor.occurrences) {
      if (!canonicalByPosition.has(occurrence.position_id)) {
        canonicalByPosition.set(occurrence.position_id, occurrence.id);
      }
    }
    const seenEdges = new Set<string>();
    return editor.occurrences.flatMap((occurrence) => {
      if (occurrence.parent_id === null) {
        return canonicalByPosition.get(occurrence.position_id) === occurrence.id
          ? [occurrence]
          : [];
      }
      const parent = byId.get(occurrence.parent_id);
      const parentId = parent
        ? (canonicalByPosition.get(parent.position_id) ?? occurrence.parent_id)
        : occurrence.parent_id;
      const edgeKey = `${parentId}:${occurrence.inbound_uci ?? occurrence.id}:${occurrence.position_id}`;
      if (seenEdges.has(edgeKey)) return [];
      seenEdges.add(edgeKey);
      return [{ ...occurrence, parent_id: parentId }];
    });
  }, [byId, course?.mode, editor]);
  const sectionAnalysisFens = useMemo(
    () =>
      Array.from(
        new Set(
          (editor?.occurrences ?? [])
            .filter((occurrence) => occurrence.module_id === moduleId)
            .map((occurrence) => occurrence.full_fen),
        ),
      ),
    [editor, moduleId],
  );

  useEffect(
    () => () => {
      sectionAnalysisController.current?.abort();
    },
    [],
  );

  async function analyzeCurrentSection(
    parameters: EngineParameters,
    fens: string[],
  ) {
    if (!moduleId || !fens.length || sectionAnalysisProgress?.running) return;
    const sectionId = moduleId;
    const sectionTitle =
      modules.find((item) => item.id === sectionId)?.title ?? '当前小节';
    const controller = new AbortController();
    sectionAnalysisController.current?.abort();
    sectionAnalysisController.current = controller;
    setSectionAnalysisProgress({
      sectionId,
      sectionTitle,
      completed: 0,
      failed: 0,
      total: fens.length,
      running: true,
      checking: true,
      cached: 0,
      lookupFailed: false,
    });

    let missingFens: string[];
    try {
      const lookup = await requestJson<AnalysisCacheLookup>(
        '/api/engine/analyses/cache-lookup',
        {
          method: 'POST',
          signal: controller.signal,
          body: JSON.stringify({ fens, parameters }),
        },
      );
      missingFens = lookup.missing_fens;
      setSectionAnalysisProgress({
        sectionId,
        sectionTitle,
        completed: 0,
        failed: 0,
        total: missingFens.length,
        running: missingFens.length > 0,
        checking: false,
        cached: lookup.cached_fens.length,
        lookupFailed: false,
      });
    } catch {
      if (controller.signal.aborted) return;
      setSectionAnalysisProgress({
        sectionId,
        sectionTitle,
        completed: 0,
        failed: 0,
        total: 0,
        running: false,
        checking: false,
        cached: 0,
        lookupFailed: true,
      });
      sectionAnalysisController.current = undefined;
      return;
    }
    if (!missingFens.length) {
      sectionAnalysisController.current = undefined;
      return;
    }

    let completed = 0;
    let failed = 0;
    for (const position of missingFens) {
      if (controller.signal.aborted) return;
      try {
        await requestJson('/api/engine/analyses', {
          method: 'POST',
          signal: controller.signal,
          body: JSON.stringify({ fen: position, parameters }),
        });
      } catch {
        if (controller.signal.aborted) return;
        failed += 1;
      }
      completed += 1;
      setSectionAnalysisProgress({
        sectionId,
        sectionTitle,
        completed,
        failed,
        total: missingFens.length,
        running: completed < missingFens.length,
        checking: false,
        cached: fens.length - missingFens.length,
        lookupFailed: false,
      });
    }
    sectionAnalysisController.current = undefined;
  }

  const explorerEntries = useMemo(() => {
    const entries: Array<{ module: CourseModule; occurrence: Occurrence }> = [];
    const seenPositions = new Set<string>();
    for (const item of modules) {
      const root = editor?.occurrences.find(
        (occurrence) =>
          occurrence.module_id === item.id && occurrence.parent_id === null,
      );
      if (!root || seenPositions.has(root.position_id)) continue;
      seenPositions.add(root.position_id);
      entries.push({ module: item, occurrence: root });
    }
    return entries;
  }, [editor, modules]);
  const current = occurrenceId ? byId.get(occurrenceId) : undefined;
  const candidates = useMemo(() => {
    if (!editor || !current) return [];
    const parentIds = new Set(
      course?.mode === 'opening_explorer'
        ? editor.occurrences
            .filter((item) => item.position_id === current.position_id)
            .map((item) => item.id)
        : [current.id],
    );
    const ordered = editor.occurrences
      .filter((item) => item.parent_id && parentIds.has(item.parent_id))
      .sort((a, b) => {
        const aCurrent = a.parent_id === current.id ? 0 : 1;
        const bCurrent = b.parent_id === current.id ? 0 : 1;
        return aCurrent - bCurrent || a.sort_order - b.sort_order;
      });
    const merged = new Map<string, (typeof ordered)[number]>();
    for (const item of ordered) {
      const key = `${item.inbound_uci ?? item.id}:${item.position_id}`;
      if (!merged.has(key)) merged.set(key, item);
    }
    return [...merged.values()];
  }, [course?.mode, current, editor]);
  const transpositionCount = useMemo(() => {
    if (!current) return 0;
    const matching =
      editor?.occurrences.filter(
        (item) => item.position_id === current.position_id,
      ) ?? [];
    if (course?.mode !== 'opening_explorer') return matching.length;
    return new Set(
      matching.map(
        (item) => `${item.parent_id ?? 'root'}:${item.inbound_uci ?? ''}`,
      ),
    ).size;
  }, [course?.mode, current, editor]);
  const boardSquareStyles = useMemo(
    () =>
      current
        ? lichessSquareStyles(
            pendingFen ?? current.full_fen,
            selectedSquare,
            current.inbound_uci,
          )
        : {},
    [current, pendingFen, selectedSquare],
  );
  const currentNotes = useMemo(() => {
    const occurrenceIds = new Set(
      course?.mode === 'opening_explorer' && current
        ? (editor?.occurrences ?? [])
            .filter((item) => item.position_id === current.position_id)
            .map((item) => item.id)
        : occurrenceId
          ? [occurrenceId]
          : [],
    );
    return (editor?.notes ?? []).filter(
      (note) =>
        note.target.kind === 'occurrence' &&
        occurrenceIds.has(note.target.occurrence_id),
    );
  }, [course?.mode, current, editor, occurrenceId]);
  const editableNote = currentNotes.find(
    (note) =>
      note.source_note_id === null &&
      note.target.kind === 'occurrence' &&
      note.target.occurrence_id === occurrenceId,
  );
  const referenceNotes = currentNotes.filter(
    (note) => note.source_note_id !== null,
  );
  const sourcesBySpanId = useMemo(
    () =>
      new Map(
        citableSources.map((item) => [item.source_span.id, item] as const),
      ),
    [citableSources],
  );
  const pdfPreviews = useMemo(() => {
    if (!pdfAssets || !pdfExtractions || !pdfDocuments) return [];
    const result: Array<{
      spanId: string;
      page: number;
      title: string;
      contentUrl: string;
    }> = [];
    for (const citable of citableSources) {
      const span = citable.source_span;
      if (!courseSourceSpanIds.has(span.id)) continue;
      if (span.locator.kind !== 'page' || span.source_file_id === null)
        continue;
      const page = span.locator.page_number;
      const asset = pdfAssets.items.find(
        (item) =>
          item.source_file_id === span.source_file_id &&
          item.source_version_id === span.source_version_id,
      );
      if (!asset) continue;
      const document = pdfDocuments.items.find(
        (item) =>
          item.pdf_asset_id === asset.id &&
          item.first_page <= page &&
          item.last_page >= page,
      );
      const run = pdfExtractions.items.find(
        (item) =>
          item.pdf_asset_id === asset.id &&
          item.first_page <= page &&
          item.last_page >= page &&
          item.job.status === 'succeeded' &&
          item.candidate !== null,
      );
      const targetId = document?.id ?? run?.id;
      if (!targetId) continue;
      result.push({
        spanId: span.id,
        page,
        title: citable.source.title,
        contentUrl: `/api/pdf-extractions/${targetId}/review/pages/${page}`,
      });
    }
    return result;
  }, [
    citableSources,
    courseSourceSpanIds,
    pdfAssets,
    pdfDocuments,
    pdfExtractions,
  ]);
  const sourcePageBySpanId = useMemo(
    () => new Map(pdfPreviews.map((item) => [item.spanId, item.page] as const)),
    [pdfPreviews],
  );
  const activePdfPreview =
    pdfPreviews.find((item) => item.spanId === activeSourceSpanId) ??
    pdfPreviews[0];

  function selectSourcePreview(spanId: string) {
    if (!sourcePageBySpanId.has(spanId)) return;
    setActiveSourceSpanId(spanId);
    setLeftPaneMode('source');
  }
  const contextNote = referenceNotes.find((note) => note.id === contextNoteId);
  const contextEditorKey =
    contextNote?.source_module_id && contextNote.source_course_id
      ? `/api/courses/${contextNote.source_course_id}/editor/${contextNote.source_module_id}`
      : null;
  const { data: contextEditor, error: contextEditorError } =
    useSWR<ModuleEditor>(contextEditorKey, fetchJson);
  const contextBlocks = useMemo(() => {
    if (!contextEditor || !contextNote?.source_note_id) return [];
    const anchor = contextEditor.content_blocks.findIndex(
      (block) =>
        block.kind === 'knowledge_note' &&
        block.knowledge_note_id === contextNote.source_note_id,
    );
    const candidates =
      anchor < 0
        ? contextEditor.content_blocks
        : contextEditor.content_blocks.slice(
            Math.max(0, anchor - 2),
            Math.min(contextEditor.content_blocks.length, anchor + 3),
          );
    return candidates.filter(
      (block) => block.kind === 'section_header' || block.kind === 'narrative',
    );
  }, [contextEditor, contextNote?.source_note_id]);
  const serverDraft = useMemo(
    () => ({
      markdown: editableNote?.markdown ?? '',
      sourceSpanIds: [...(editableNote?.source_span_ids ?? [])],
    }),
    [editableNote?.markdown, editableNote?.source_span_ids],
  );
  useEffect(() => {
    dispatchDraft({ type: 'reset', draft: serverDraft });
    setBaseline(serverDraft);
    setSaveError(undefined);
  }, [editableNote?.id, editableNote?.version, occurrenceId, serverDraft]);
  const dirty =
    draft.present.markdown !== baseline.markdown ||
    draft.present.sourceSpanIds.join('\0') !==
      baseline.sourceSpanIds.join('\0');
  const historyKey =
    historyOpen && editableNote
      ? `/api/history/knowledge_note/${editableNote.id}`
      : null;
  const { data: history, error: historyError } = useSWR<ContentHistory>(
    historyKey,
    fetchJson,
  );

  function selectOccurrence(id: string) {
    const selected = byId.get(id);
    if (course?.mode === 'opening_explorer' && selected?.module_id) {
      setModuleId(selected.module_id);
    }
    setOccurrenceId(id);
    setPendingFen(undefined);
    setSelectedSquare(undefined);
  }

  function submitMove(source: string, target: string): boolean {
    if (!current || !editor) return false;
    const game = new Chess(pendingFen ?? current.full_fen);
    let move;
    try {
      move = game.move({ from: source, to: target, promotion: 'q' });
    } catch {
      return false;
    }
    if (!move) return false;
    const uci = `${source}${target}${move.promotion ?? ''}`;
    const existing = pendingFen
      ? undefined
      : candidates.find((item) => item.inbound_uci === uci);
    if (existing) {
      selectOccurrence(existing.id);
      return true;
    }
    setPendingFen(game.fen());
    if (!recordBoardMoves) return true;
    void requestJson<Occurrence>('/api/occurrences', {
      method: 'POST',
      body: JSON.stringify({
        kind: 'move',
        parent_occurrence_id: current.id,
        uci,
        sort_order: candidates.length,
      }),
    })
      .then(async (created) => {
        let createdIsVisible = false;
        if (course?.mode === 'opening_explorer') {
          const refreshed = await mutateExplorerEditors();
          createdIsVisible =
            refreshed?.some((item) =>
              item.occurrences.some(
                (occurrence) => occurrence.id === created.id,
              ),
            ) ?? false;
        } else {
          const refreshed = await mutateModuleEditor();
          createdIsVisible =
            refreshed?.occurrences.some(
              (occurrence) => occurrence.id === created.id,
            ) ?? false;
        }
        if (!createdIsVisible) {
          throw new Error('保存后的棋步没有出现在当前小节中，请刷新页面后重试');
        }
        setOccurrenceId(created.id);
        setPendingFen(undefined);
      })
      .catch((error: unknown) => {
        setPendingFen(undefined);
        void message.error(
          error instanceof Error ? error.message : '保存棋步失败',
        );
      });
    return true;
  }

  function onPieceDrop(source: string, target: string): boolean {
    setSelectedSquare(undefined);
    return submitMove(source, target);
  }

  function selectOwnPiece(square: string) {
    if (!current) return;
    const game = new Chess(pendingFen ?? current.full_fen);
    const piece = game.get(square as Parameters<typeof game.get>[0]);
    setSelectedSquare(piece?.color === game.turn() ? square : undefined);
  }

  function onSquareClick(square: string) {
    if (!current) return;
    if (!selectedSquare) {
      selectOwnPiece(square);
      return;
    }
    if (selectedSquare === square) {
      setSelectedSquare(undefined);
      return;
    }
    if (submitMove(selectedSquare, square)) {
      setSelectedSquare(undefined);
      return;
    }
    selectOwnPiece(square);
  }

  async function createModule(values: {
    title: string;
    start_fen: string;
    parent_id?: string;
  }) {
    await requestJson<CourseModule>('/api/course-modules', {
      method: 'POST',
      body: JSON.stringify({
        ...values,
        course_id: courseId,
        sort_order: modules.length,
      }),
    });
    setModuleModal(false);
    form.resetFields();
    await mutateModules();
    void message.success(
      course?.mode === 'opening_explorer' ? '入口局面已创建' : '章节已创建',
    );
  }

  async function applyMoveAction(
    action: CourseMoveAction,
    occurrence: ModuleEditor['occurrences'][number],
  ) {
    let nag: number | null | undefined;
    if (action === 'set_nag') {
      const input = window.prompt(
        '输入招法评注：!、?、!!、??、!?、?!；留空清除',
        occurrence.nag === null ? '' : nagSymbol(occurrence.nag),
      );
      if (input === null) return;
      const normalized = input.trim();
      const mapped = (
        {
          '!': 1,
          '?': 2,
          '!!': 3,
          '??': 4,
          '!?': 5,
          '?!': 6,
        } as Record<string, number>
      )[normalized];
      if (normalized && mapped === undefined) {
        void message.warning('请输入 !、?、!!、??、!?、?!，或留空清除');
        return;
      }
      nag = normalized ? mapped : null;
    }
    if (
      action === 'delete_subtree' &&
      !window.confirm(
        '确定从这步开始删除整条分支吗？此操作会使相关探索器来源失效。',
      )
    ) {
      return;
    }
    try {
      const result = await requestJson<{
        selected_occurrence_id: string;
      }>(`/api/occurrences/${occurrence.id}/commands`, {
        method: 'POST',
        body: JSON.stringify({
          kind: action,
          expected_version: occurrence.version,
          ...(action === 'set_nag' ? { nag } : {}),
        }),
      });
      if (course?.mode === 'opening_explorer') await mutateExplorerEditors();
      else await mutateModuleEditor();
      setOccurrenceId(result.selected_occurrence_id);
      setPendingFen(undefined);
    } catch (error: unknown) {
      void message.error(
        error instanceof Error ? error.message : '棋谱修改失败',
      );
    }
  }

  async function renameModule(item: CourseModule) {
    const title = window.prompt('重命名小节', item.title)?.trim();
    if (!title || title === item.title) return;
    try {
      await requestJson(`/api/course-modules/${item.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ expected_version: item.version, title }),
      });
      await Promise.all([mutateModules(), mutateModuleEditor()]);
    } catch (error: unknown) {
      void message.error(error instanceof Error ? error.message : '重命名失败');
    }
  }

  async function renameCourse() {
    if (!course) return;
    const title = window.prompt('重命名课程', course.title)?.trim();
    if (!title || title === course.title) return;
    try {
      const updated = await requestJson<Course>(`/api/courses/${course.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ expected_version: course.version, title }),
      });
      await mutateCourse(updated, { revalidate: false });
    } catch (error: unknown) {
      void message.error(
        error instanceof Error ? error.message : '重命名课程失败',
      );
    }
  }

  async function deleteCourse() {
    if (
      !course ||
      !window.confirm(
        `确定删除课程“${course.title}”吗？课程内容会被归档，不会删除共享局面数据。`,
      )
    ) {
      return;
    }
    try {
      await requestJson<Course>(`/api/courses/${course.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          expected_version: course.version,
          archived: true,
        }),
      });
      void message.success('课程已删除');
      navigate('/learn', { replace: true });
    } catch (error: unknown) {
      void message.error(
        error instanceof Error ? error.message : '删除课程失败',
      );
    }
  }

  async function reorderSiblingModules(orderedIds: string[]) {
    if (reorderingModules) return;
    const orderById = new Map(orderedIds.map((id, index) => [id, index]));
    const changes = modules.flatMap((item) => {
      const sortOrder = orderById.get(item.id);
      return sortOrder === undefined || sortOrder === item.sort_order
        ? []
        : [{ item, sortOrder }];
    });
    if (changes.length === 0) return;

    setReorderingModules(true);
    await mutateModules(
      modules.map((item) => {
        const sortOrder = orderById.get(item.id);
        return sortOrder === undefined
          ? item
          : { ...item, sort_order: sortOrder };
      }),
      { revalidate: false },
    );
    try {
      for (const { item, sortOrder } of changes) {
        await requestJson<CourseModule>(`/api/course-modules/${item.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            expected_version: item.version,
            sort_order: sortOrder,
          }),
        });
      }
      await mutateModules();
    } catch (error: unknown) {
      await mutateModules();
      void message.error(
        error instanceof Error ? error.message : '调整小节顺序失败',
      );
    } finally {
      setReorderingModules(false);
    }
  }

  async function deleteModule(item: CourseModule) {
    const childCount = modules.filter(
      (candidate) => candidate.parent_id === item.id,
    ).length;
    if (
      !window.confirm(
        childCount
          ? `确定删除“${item.title}”及其 ${childCount} 个下级小节吗？`
          : `确定删除“${item.title}”吗？`,
      )
    ) {
      return;
    }
    try {
      await requestJson(`/api/course-modules/${item.id}/archive-tree`, {
        method: 'POST',
        body: JSON.stringify({ expected_version: item.version }),
      });
      if (
        moduleId === item.id ||
        isModuleDescendant(modules, moduleId, item.id)
      ) {
        setModuleId(undefined);
        setOccurrenceId(undefined);
      }
      await mutateModules();
      void message.success('小节已删除；相关探索器来源已失效');
    } catch (error: unknown) {
      void message.error(
        error instanceof Error ? error.message : '删除小节失败',
      );
    }
  }

  async function saveNote() {
    if (!current || !draft.present.markdown.trim()) return;
    setSaving(true);
    setSaveError(undefined);
    try {
      if (editableNote) {
        await requestJson(`/api/knowledge-notes/${editableNote.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            expected_version: editableNote.version,
            markdown: draft.present.markdown,
            source_span_ids: draft.present.sourceSpanIds,
          }),
        });
      } else {
        const endpoint =
          course?.mode === 'traditional' && moduleId
            ? `/api/course-modules/${moduleId}/knowledge-note-blocks`
            : '/api/knowledge-notes';
        await requestJson(endpoint, {
          method: 'POST',
          body: JSON.stringify({
            occurrence_id: current.id,
            markdown: draft.present.markdown,
            source_span_ids: draft.present.sourceSpanIds,
            review_status: 'approved',
          }),
        });
      }
      if (course?.mode === 'opening_explorer') {
        await mutateExplorerEditors();
      } else {
        await mutateModuleEditor();
      }
      void message.success('说明已保存');
    } catch (error: unknown) {
      setSaveError(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  async function createNarrative() {
    if (!moduleId || !narrativeMarkdown.trim()) return;
    const nextSortOrder =
      Math.max(
        -1,
        ...(editor?.content_blocks.map((block) => block.sort_order) ?? []),
      ) + 1;
    await requestJson('/api/course-content-blocks', {
      method: 'POST',
      body: JSON.stringify({
        module_id: moduleId,
        kind: 'narrative',
        sort_order: nextSortOrder,
        markdown: narrativeMarkdown,
        source_span_ids: narrativeSourceSpanIds,
      }),
    });
    setNarrativeModal(false);
    setNarrativeMarkdown('');
    setNarrativeSourceSpanIds([]);
    await mutateModuleEditor();
    void message.success('章节正文已添加');
  }

  function sourceLabel(spanId: string) {
    const citable = sourcesBySpanId.get(spanId);
    if (!citable) return '来源片段';
    const locator = citable.source_span.locator;
    if (locator.kind === 'page') {
      return `${citable.source.title} · 第 ${locator.page_number} 页`;
    }
    if (locator.kind === 'video') {
      return `${citable.source.title} · ${Math.floor(locator.start_ms / 1000)}s`;
    }
    return citable.source.title;
  }

  async function publishModule() {
    if (!moduleId || !publishTarget) return;
    await requestJson(`/api/courses/${publishTarget}/publish-modules`, {
      method: 'POST',
      body: JSON.stringify({ module_ids: [moduleId] }),
    });
    setPublishModal(false);
    setPublishTarget(undefined);
    void message.success('章节已发布到开局探索器');
  }

  async function importPgn() {
    if (!course || !importText.trim()) return;
    setImporting(true);
    setImportError(undefined);
    try {
      await requestJson('/api/pgn/imports', {
        method: 'POST',
        headers: { 'Idempotency-Key': importKey },
        body: JSON.stringify({
          pgn: importText,
          destination: {
            kind: 'existing_course',
            course_id: course.id,
            expected_version: course.version,
          },
          ...(importSourceTitle.trim()
            ? { source_title: importSourceTitle.trim() }
            : {}),
        }),
      });
      await Promise.all([mutateCourse(), mutateModules()]);
      setImportModal(false);
      setImportText('');
      setImportSourceTitle('');
      void message.success('PGN 已导入');
    } catch (error: unknown) {
      setImportError(error instanceof Error ? error.message : 'PGN 导入失败');
    } finally {
      setImporting(false);
    }
  }

  if (courseError) return <Alert type="error" title="课程不存在或无法读取" />;
  if (!course)
    return (
      <div className="grid min-h-[70vh] place-items-center">
        <Spin size="large" />
      </div>
    );

  return (
    <main className="px-4 py-5 xl:px-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Space>
          <Link to="/learn">← 返回课程</Link>
          <Typography.Title className="m-0!" level={3}>
            {course.title}
          </Typography.Title>
          <Dropdown
            trigger={['click']}
            menu={{
              items: [
                { key: 'rename', label: '重命名课程' },
                { key: 'delete', label: '删除课程', danger: true },
              ],
              onClick: ({ key }) => {
                if (key === 'rename') void renameCourse();
                else void deleteCourse();
              },
            }}
          >
            <Button
              type="text"
              aria-label={`${course.title} 设置`}
              title="课程设置"
            >
              ⚙
            </Button>
          </Dropdown>
          <Tag color={course.mode === 'traditional' ? 'blue' : 'purple'}>
            {course.mode === 'traditional' ? '传统课程' : '开局探索器'}
          </Tag>
        </Space>
        <Space>
          {course.mode === 'traditional' ? (
            <Button
              onClick={() => {
                setImportKey(crypto.randomUUID());
                setImportError(undefined);
                setImportModal(true);
              }}
            >
              导入 PGN
            </Button>
          ) : null}
          {moduleId ? (
            <a
              href={`/api/courses/${course.id}/pgn?module_id=${moduleId}`}
              download
            >
              <Button>
                {course.mode === 'opening_explorer'
                  ? '导出探索图 PGN'
                  : '导出章节 PGN'}
              </Button>
            </a>
          ) : null}
          {moduleId && current ? (
            <a
              href={`/api/courses/${course.id}/pgn?module_id=${moduleId}&leaf_occurrence_id=${current.id}`}
              download
            >
              <Button>导出当前线</Button>
            </a>
          ) : null}
          {course.mode === 'traditional' && moduleId ? (
            <Button onClick={() => setPublishModal(true)}>
              发布到开局探索器
            </Button>
          ) : null}
          <Button onClick={() => setModuleModal(true)}>
            {course.mode === 'opening_explorer' ? '添加入口局面' : '新建章节'}
          </Button>
        </Space>
      </div>
      {editorError ? (
        <Alert
          className="mb-4"
          type="error"
          showIcon
          title="编辑器数据加载失败"
        />
      ) : null}
      <div className="course-workbench-grid">
        <Card
          title={leftPaneMode === 'chapters' ? '章节' : '原书页面'}
          size="small"
          className="course-workbench-pane course-left-pane"
          extra={
            course.mode === 'traditional' ? (
              <Space.Compact>
                <Button
                  size="small"
                  type={leftPaneMode === 'chapters' ? 'primary' : 'default'}
                  onClick={() => setLeftPaneMode('chapters')}
                >
                  目录
                </Button>
                <Button
                  size="small"
                  type={leftPaneMode === 'source' ? 'primary' : 'default'}
                  disabled={!activePdfPreview}
                  onClick={() => setLeftPaneMode('source')}
                >
                  原文
                </Button>
              </Space.Compact>
            ) : null
          }
        >
          {leftPaneMode === 'source' && activePdfPreview ? (
            <figure className="m-0 flex min-h-0 flex-col">
              <img
                src={activePdfPreview.contentUrl}
                alt={`${activePdfPreview.title} 第 ${activePdfPreview.page} 页`}
                className="mx-auto block max-h-[calc(100vh-15rem)] max-w-full object-contain"
              />
              <figcaption className="mt-2 text-center text-xs text-stone-500">
                {activePdfPreview.title} · 第 {activePdfPreview.page} 页
              </figcaption>
            </figure>
          ) : course.mode === 'opening_explorer' ? (
            <>
              <Alert
                type="success"
                showIcon
                title="合并探索图"
                description="已发布章节会按共同局面和候选着自动合并；来源观点显示在对应局面。"
              />
              {explorerEntries.length > 1 ? (
                <div className="mt-4">
                  <Typography.Text type="secondary">
                    无法连通的入口局面
                  </Typography.Text>
                  <div className="mt-2 grid gap-2">
                    {explorerEntries.map((entry, index) => (
                      <Button
                        key={entry.occurrence.position_id}
                        type={
                          entry.module.id === moduleId ? 'primary' : 'default'
                        }
                        onClick={() => selectOccurrence(entry.occurrence.id)}
                      >
                        入口局面 {index + 1}
                      </Button>
                    ))}
                  </div>
                </div>
              ) : (
                <Typography.Paragraph type="secondary" className="mt-4">
                  当前只有一个连通入口，不再按来源章节拆分。
                </Typography.Paragraph>
              )}
            </>
          ) : modules.length ? (
            <ModuleDirectory
              modules={modules}
              selectedId={moduleId}
              expandedIds={expandedModuleIds}
              onToggle={(id) =>
                setExpandedModuleIds((current) => {
                  const next = new Set(current);
                  if (next.has(id)) next.delete(id);
                  else next.add(id);
                  return next;
                })
              }
              onSelect={(id) => {
                setModuleId(id);
                setOccurrenceId(undefined);
              }}
              onRename={(item) => void renameModule(item)}
              onDelete={(item) => void deleteModule(item)}
              onReorder={(orderedIds) => void reorderSiblingModules(orderedIds)}
              reordering={reorderingModules}
            />
          ) : (
            <Empty description="先创建一个章节" />
          )}
        </Card>
        <section className="course-board-pane min-w-0">
          {current ? (
            <>
              <div className="mx-auto max-w-[500px]">
                <Chessboard
                  id="course-editor-board"
                  position={pendingFen ?? current.full_fen}
                  boardOrientation={boardOrientation}
                  animationDuration={FAST_MOVE_ANIMATION_MS}
                  onPieceDrop={onPieceDrop}
                  onPieceDragBegin={(_, source) => selectOwnPiece(source)}
                  onPieceDragEnd={() => setSelectedSquare(undefined)}
                  onSquareClick={onSquareClick}
                  autoPromoteToQueen
                  customSquareStyles={boardSquareStyles}
                  customArrows={engineArrows}
                  customBoardStyle={{
                    borderRadius: '8px',
                    boxShadow: '0 12px 30px rgba(28,25,23,.16)',
                  }}
                />
              </div>
              <div className="mx-auto mt-3 max-w-[500px]">
                <CourseEnginePanel
                  fen={pendingFen ?? current.full_fen}
                  sectionFens={sectionAnalysisFens}
                  sectionProgress={sectionAnalysisProgress}
                  onAnalyzeSection={analyzeCurrentSection}
                  onArrowsChange={setEngineArrows}
                />
              </div>
            </>
          ) : (
            <Empty description="选择带起始局面的章节" />
          )}
        </section>
        <Card
          title={course.mode === 'traditional' ? '课程内容' : '探索棋谱'}
          size="small"
          className="course-workbench-pane course-reading-pane"
          extra={
            course.mode === 'traditional' ? (
              <Space size="small">
                {transpositionCount > 1 ? (
                  <Tag color="gold">转置 × {transpositionCount}</Tag>
                ) : null}
                <Space.Compact>
                  <Button
                    size="small"
                    type={readingMode ? 'primary' : 'default'}
                    onClick={() => setReadingMode(true)}
                  >
                    阅读
                  </Button>
                  <Button
                    size="small"
                    type={!readingMode ? 'primary' : 'default'}
                    onClick={() => setReadingMode(false)}
                  >
                    编辑
                  </Button>
                </Space.Compact>
              </Space>
            ) : transpositionCount > 1 ? (
              <Tag color="gold">转置 × {transpositionCount}</Tag>
            ) : null
          }
        >
          <div className="course-reading-scroll" aria-label="课程内容滚动区">
            <article
              className="course-reading-flow"
              aria-label="课程正文与棋谱"
            >
              {!readingMode && course.mode === 'traditional' ? (
                <div className="mb-3 flex justify-end">
                  <Button size="small" onClick={() => setNarrativeModal(true)}>
                    添加叙述正文
                  </Button>
                </div>
              ) : null}
              {editor?.content_blocks.map((block) => {
                if (block.kind === 'knowledge_note') return null;
                if (block.kind === 'move_sequence') {
                  return block.root_occurrence_id ? (
                    <CourseScore
                      key={block.id}
                      occurrences={scoreOccurrences}
                      notes={(editor.notes ?? []).filter(
                        (note) => note.source_note_id === null,
                      )}
                      rootId={block.root_occurrence_id}
                      currentId={current?.id}
                      sourcePageBySpanId={sourcePageBySpanId}
                      onSelectOccurrence={selectOccurrence}
                      onSelectSource={selectSourcePreview}
                      onMoveAction={(action, occurrence) =>
                        void applyMoveAction(action, occurrence)
                      }
                    />
                  ) : null;
                }
                return (
                  <section key={block.id} className="course-reading-prose">
                    {block.kind === 'section_header' ? (
                      <Typography.Title level={4}>
                        {block.heading}
                      </Typography.Title>
                    ) : null}
                    {block.kind === 'narrative' && block.markdown ? (
                      <div
                        onContextMenu={(event) => {
                          const spanId = block.source_span_ids.find((id) =>
                            sourcePageBySpanId.has(id),
                          );
                          if (!spanId) return;
                          event.preventDefault();
                          selectSourcePreview(spanId);
                        }}
                      >
                        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
                          {block.markdown}
                        </ReactMarkdown>
                      </div>
                    ) : null}
                  </section>
                );
              })}
              {editor &&
              !editor.content_blocks.some(
                (block) => block.kind === 'move_sequence',
              ) ? (
                editor.occurrences.find((item) => item.parent_id === null) ? (
                  <CourseScore
                    occurrences={scoreOccurrences}
                    notes={(editor.notes ?? []).filter(
                      (note) => note.source_note_id === null,
                    )}
                    rootId={
                      editor.occurrences.find(
                        (item) => item.parent_id === null,
                      )!.id
                    }
                    currentId={current?.id}
                    sourcePageBySpanId={sourcePageBySpanId}
                    onSelectOccurrence={selectOccurrence}
                    onSelectSource={selectSourcePreview}
                    onMoveAction={(action, occurrence) =>
                      void applyMoveAction(action, occurrence)
                    }
                  />
                ) : (
                  <Empty description="本章还没有内容" />
                )
              ) : null}
            </article>
            {current ? (
              <>
                {referenceNotes.length ? (
                  <div className="mt-4">
                    <Typography.Text strong>来源观点</Typography.Text>
                    {referenceNotes.map((note) => (
                      <Card key={note.id} size="small" className="mt-2">
                        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
                          {note.rendered_markdown}
                        </ReactMarkdown>
                        <Link
                          to={`/learn/${note.source_course_id}?module=${note.source_module_id ?? ''}&occurrence=${note.source_occurrence_id}`}
                        >
                          跳转到原始条目
                        </Link>
                        <Button
                          className="ml-2"
                          type="link"
                          disabled={!note.source_module_id}
                          onClick={() => setContextNoteId(note.id)}
                        >
                          查看原文上下文
                        </Button>
                      </Card>
                    ))}
                  </div>
                ) : null}
                {!readingMode || course.mode === 'opening_explorer' ? (
                  <>
                    <Divider />
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <Typography.Text strong>
                        {current.parent_id ? '着法与局面说明' : '局面说明'}
                      </Typography.Text>
                      <Space size="small">
                        <Button
                          size="small"
                          disabled={draft.past.length === 0}
                          onClick={() => dispatchDraft({ type: 'undo' })}
                        >
                          撤销
                        </Button>
                        <Button
                          size="small"
                          disabled={draft.future.length === 0}
                          onClick={() => dispatchDraft({ type: 'redo' })}
                        >
                          重做
                        </Button>
                        <Button
                          size="small"
                          disabled={!editableNote}
                          onClick={() => setHistoryOpen(true)}
                        >
                          历史
                        </Button>
                      </Space>
                    </div>
                    {saveError ? (
                      <Alert
                        className="mb-3"
                        type="error"
                        showIcon
                        title="说明尚未保存"
                        description={saveError}
                        action={
                          <Button size="small" onClick={() => void saveNote()}>
                            重试
                          </Button>
                        }
                      />
                    ) : null}
                    <Input.TextArea
                      aria-label="Markdown 说明"
                      value={draft.present.markdown}
                      autoSize={{ minRows: 5, maxRows: 12 }}
                      placeholder="用 Markdown 写下计划、解释或记忆提示"
                      onChange={(event) =>
                        dispatchDraft({
                          type: 'markdown',
                          markdown: event.target.value,
                        })
                      }
                    />
                    <Select
                      aria-label="关联来源"
                      className="mt-3 w-full"
                      mode="multiple"
                      placeholder="关联一个或多个手工来源"
                      value={draft.present.sourceSpanIds}
                      onChange={(sourceSpanIds) =>
                        dispatchDraft({ type: 'sources', sourceSpanIds })
                      }
                      options={citableSources.map((item) => ({
                        value: item.source_span.id,
                        label: item.source.title,
                      }))}
                    />
                    <div className="mt-3 rounded-md bg-stone-50 p-3">
                      <Typography.Text type="secondary">
                        安全预览
                      </Typography.Text>
                      {draft.present.markdown ? (
                        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
                          {draft.present.markdown}
                        </ReactMarkdown>
                      ) : (
                        <Typography.Paragraph
                          type="secondary"
                          className="mb-0!"
                        >
                          还没有说明
                        </Typography.Paragraph>
                      )}
                    </div>
                    <div className="mt-3 flex items-center justify-between">
                      <Typography.Text type={dirty ? 'warning' : 'secondary'}>
                        {dirty ? '有未保存修改' : '已与服务器同步'}
                      </Typography.Text>
                      <Button
                        type="primary"
                        loading={saving}
                        disabled={!dirty || !draft.present.markdown.trim()}
                        onClick={() => void saveNote()}
                      >
                        保存说明
                      </Button>
                    </div>
                  </>
                ) : null}
              </>
            ) : null}
          </div>
          {scoreRootId ? (
            <CourseScoreControls
              occurrences={scoreOccurrences}
              rootId={scoreRootId}
              currentId={current?.id}
              onSelectOccurrence={selectOccurrence}
              recordMoves={recordBoardMoves}
              onRecordMovesChange={(enabled) => {
                setRecordBoardMoves(enabled);
                setPendingFen(undefined);
                setSelectedSquare(undefined);
              }}
              boardOrientation={boardOrientation}
              onFlipBoard={() =>
                setBoardOrientation((current) =>
                  current === 'white' ? 'black' : 'white',
                )
              }
            />
          ) : null}
        </Card>
      </div>
      <Modal
        title="添加叙述正文"
        open={narrativeModal}
        okText="添加到本章"
        okButtonProps={{ disabled: !narrativeMarkdown.trim() }}
        onOk={() => void createNarrative()}
        onCancel={() => setNarrativeModal(false)}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          叙述正文不绑定具体局面，会按章节顺序显示；可同时保留棋书或视频来源。
        </Typography.Paragraph>
        <Input.TextArea
          aria-label="叙述正文 Markdown"
          value={narrativeMarkdown}
          autoSize={{ minRows: 8, maxRows: 18 }}
          placeholder="用 Markdown 输入这一段连续讲解"
          onChange={(event) => setNarrativeMarkdown(event.target.value)}
        />
        <Select
          aria-label="叙述正文来源"
          className="mt-3 w-full"
          mode="multiple"
          placeholder="关联一个或多个来源片段"
          value={narrativeSourceSpanIds}
          onChange={setNarrativeSourceSpanIds}
          options={citableSources.map((item) => ({
            value: item.source_span.id,
            label: item.source.title,
          }))}
        />
      </Modal>
      <Drawer
        title="原文上下文"
        size="large"
        open={Boolean(contextNoteId)}
        onClose={() => setContextNoteId(undefined)}
        destroyOnHidden
      >
        {contextEditorError ? (
          <Alert type="error" showIcon title="无法读取原章节上下文" />
        ) : !contextEditor ? (
          <Spin />
        ) : (
          <>
            <Typography.Title level={4} className="mt-0!">
              {contextEditor.module.title}
            </Typography.Title>
            {contextBlocks.length ? (
              <div className="source-context-prose">
                {contextBlocks.map((block) => (
                  <section key={block.id}>
                    {block.kind === 'section_header' ? (
                      <Typography.Title level={5}>
                        {block.heading}
                      </Typography.Title>
                    ) : null}
                    {block.kind === 'narrative' && block.markdown ? (
                      <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
                        {block.markdown}
                      </ReactMarkdown>
                    ) : null}
                  </section>
                ))}
              </div>
            ) : (
              <Typography.Paragraph type="secondary">
                原章节没有与这条观点相邻的叙述正文。
              </Typography.Paragraph>
            )}
            <Divider>关联的局面说明</Divider>
            {contextNote ? (
              <>
                <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
                  {contextNote.rendered_markdown}
                </ReactMarkdown>
                <Space size={[4, 4]} wrap>
                  {contextNote.rendered_source_span_ids.map((spanId) => (
                    <Tag key={spanId} color="blue">
                      {sourceLabel(spanId)}
                    </Tag>
                  ))}
                </Space>
              </>
            ) : null}
          </>
        )}
      </Drawer>
      <Modal
        title={course.mode === 'opening_explorer' ? '添加入口局面' : '新建章节'}
        open={moduleModal}
        onCancel={() => setModuleModal(false)}
        onOk={() => form.submit()}
        okText="创建"
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            start_fen: START_FEN,
            ...(course.mode === 'opening_explorer'
              ? { title: `入口局面 ${modules.length + 1}` }
              : {}),
          }}
          onFinish={(values) =>
            void createModule(
              values as {
                title: string;
                start_fen: string;
                parent_id?: string;
              },
            )
          }
        >
          {course.mode === 'traditional' ? (
            <>
              <Form.Item
                name="title"
                label="章节名称"
                rules={[{ required: true, whitespace: true }]}
              >
                <Input />
              </Form.Item>
              <Form.Item name="parent_id" label="上级章节（可选）">
                <Select
                  allowClear
                  options={modules.map((item) => ({
                    value: item.id,
                    label: item.title,
                  }))}
                />
              </Form.Item>
            </>
          ) : (
            <Form.Item name="title" hidden>
              <Input />
            </Form.Item>
          )}
          <Form.Item
            name="start_fen"
            label="起始 FEN"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="导入 PGN 到当前课程"
        open={importModal}
        okText="导入"
        confirmLoading={importing}
        okButtonProps={{ disabled: !importText.trim() }}
        onCancel={() => setImportModal(false)}
        onOk={() => void importPgn()}
      >
        {importError ? (
          <Alert className="mb-3" type="error" showIcon title={importError} />
        ) : null}
        <Input
          aria-label="PGN 来源标题"
          className="mb-3"
          placeholder="来源标题（可选）"
          value={importSourceTitle}
          onChange={(event) => setImportSourceTitle(event.target.value)}
        />
        <Input.TextArea
          aria-label="PGN 文本"
          value={importText}
          autoSize={{ minRows: 10, maxRows: 18 }}
          placeholder={'[Event "Study"]\n\n1. e4 e5 2. Nf3 *'}
          onChange={(event) => setImportText(event.target.value)}
        />
        <Typography.Paragraph type="secondary" className="mt-3 mb-0!">
          导入由后端 python-chess 校验；失败或重试不会留下部分章节。
        </Typography.Paragraph>
      </Modal>
      <Modal
        title="发布当前章节"
        open={publishModal}
        okText="发布"
        okButtonProps={{ disabled: !publishTarget }}
        onCancel={() => setPublishModal(false)}
        onOk={() => void publishModule()}
      >
        <Typography.Paragraph>
          棋谱将复用全局局面图，已批准的说明将作为实时引用卡发布，不会复制正文。
        </Typography.Paragraph>
        <Select
          aria-label="目标开局探索器"
          className="w-full"
          placeholder="选择目标课程"
          value={publishTarget}
          onChange={setPublishTarget}
          options={explorerCourses.map((item) => ({
            value: item.id,
            label: item.title,
          }))}
        />
      </Modal>
      <Modal
        title="说明历史"
        open={historyOpen}
        footer={null}
        onCancel={() => setHistoryOpen(false)}
      >
        {historyError ? <Alert type="error" title="历史加载失败" /> : null}
        {!history ? <Spin /> : null}
        {history?.revisions.length === 0 ? (
          <Empty description="还没有更早版本" />
        ) : null}
        {history?.revisions.map((revision) => (
          <Card
            key={revision.id}
            size="small"
            className="mb-3"
            title={`版本 ${revision.entity_version}`}
          >
            <Typography.Text type="secondary">
              {new Date(revision.created_at).toLocaleString()}
            </Typography.Text>
            <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
              {typeof revision.snapshot.markdown === 'string'
                ? revision.snapshot.markdown
                : '（此版本没有 Markdown）'}
            </ReactMarkdown>
          </Card>
        ))}
      </Modal>
    </main>
  );
}

function ModuleDirectory({
  modules,
  selectedId,
  expandedIds,
  onToggle,
  onSelect,
  onRename,
  onDelete,
  onReorder,
  reordering,
}: {
  modules: CourseModule[];
  selectedId: string | undefined;
  expandedIds: Set<string>;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
  onRename: (item: CourseModule) => void;
  onDelete: (item: CourseModule) => void;
  onReorder: (orderedIds: string[]) => void;
  reordering: boolean;
}) {
  const draggedId = useRef<string>();
  const [dropIndicator, setDropIndicator] = useState<{
    id: string;
    position: 'before' | 'after';
  }>();
  const childrenByParent = new Map<string | null, CourseModule[]>();
  for (const item of modules) {
    const siblings = childrenByParent.get(item.parent_id) ?? [];
    siblings.push(item);
    childrenByParent.set(item.parent_id, siblings);
  }
  for (const siblings of childrenByParent.values()) {
    siblings.sort(
      (left, right) =>
        left.sort_order - right.sort_order ||
        left.title.localeCompare(right.title),
    );
  }

  function renderLevel(parentId: string | null, depth: number) {
    return (childrenByParent.get(parentId) ?? []).map((item) => {
      const children = childrenByParent.get(item.id) ?? [];
      const expanded = expandedIds.has(item.id);
      const indicator = dropIndicator?.id === item.id && dropIndicator.position;

      function dropPosition(event: ReactDragEvent): 'before' | 'after' {
        const bounds = event.currentTarget.getBoundingClientRect();
        return event.clientY < bounds.top + bounds.height / 2
          ? 'before'
          : 'after';
      }

      function canDrop(): boolean {
        const dragged = modules.find(
          (candidate) => candidate.id === draggedId.current,
        );
        return Boolean(
          dragged &&
          dragged.id !== item.id &&
          dragged.parent_id === item.parent_id,
        );
      }

      return (
        <li key={item.id}>
          <div
            className={`flex items-center ${item.id === selectedId ? 'bg-emerald-50' : ''} ${indicator === 'before' ? 'border-t-2 border-emerald-600' : ''} ${indicator === 'after' ? 'border-b-2 border-emerald-600' : ''}`}
            style={{ paddingLeft: `${depth * 16}px` }}
            onDragOver={(event) => {
              if (!canDrop()) return;
              event.preventDefault();
              event.dataTransfer.dropEffect = 'move';
              setDropIndicator({ id: item.id, position: dropPosition(event) });
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node)) {
                setDropIndicator(undefined);
              }
            }}
            onDrop={(event) => {
              const droppedId = draggedId.current;
              if (!canDrop() || !droppedId) return;
              event.preventDefault();
              const siblings = [
                ...(childrenByParent.get(item.parent_id) ?? []),
              ];
              const reordered = siblings.filter(
                (candidate) => candidate.id !== droppedId,
              );
              const targetIndex = reordered.findIndex(
                (candidate) => candidate.id === item.id,
              );
              const position = dropPosition(event);
              reordered.splice(
                targetIndex + (position === 'after' ? 1 : 0),
                0,
                siblings.find((candidate) => candidate.id === droppedId)!,
              );
              draggedId.current = undefined;
              setDropIndicator(undefined);
              onReorder(reordered.map((candidate) => candidate.id));
            }}
          >
            {children.length > 0 ? (
              <button
                type="button"
                aria-label={`${expanded ? '收起' : '展开'} ${item.title}`}
                aria-expanded={expanded}
                onClick={() => onToggle(item.id)}
                className="h-8 w-7 shrink-0 text-stone-500"
              >
                {expanded ? '▾' : '▸'}
              </button>
            ) : (
              <span className="block w-7 shrink-0" />
            )}
            <button
              type="button"
              draggable={!reordering}
              disabled={reordering}
              aria-label={`拖动 ${item.title}`}
              title="拖动调整同级顺序"
              onDragStart={(event) => {
                draggedId.current = item.id;
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', item.id);
              }}
              onDragEnd={() => {
                draggedId.current = undefined;
                setDropIndicator(undefined);
              }}
              className="grid h-8 w-6 shrink-0 cursor-grab place-items-center rounded text-stone-300 hover:bg-stone-100 hover:text-stone-600 active:cursor-grabbing disabled:cursor-wait"
            >
              ⠿
            </button>
            <Button
              type="text"
              className="min-w-0 flex-1 justify-start truncate text-left"
              onClick={() => onSelect(item.id)}
            >
              {item.title}
            </Button>
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  { key: 'rename', label: '重命名' },
                  { key: 'delete', label: '删除小节', danger: true },
                ],
                onClick: ({ key, domEvent }) => {
                  domEvent.stopPropagation();
                  if (key === 'rename') onRename(item);
                  else onDelete(item);
                },
              }}
            >
              <button
                type="button"
                aria-label={`${item.title} 设置`}
                onClick={(event) => event.stopPropagation()}
                className="mr-1 grid h-8 w-8 shrink-0 place-items-center rounded text-stone-400 hover:bg-stone-100 hover:text-stone-700"
              >
                ⚙
              </button>
            </Dropdown>
          </div>
          {children.length > 0 && expanded ? (
            <ul className="list-none p-0!">
              {renderLevel(item.id, depth + 1)}
            </ul>
          ) : null}
        </li>
      );
    });
  }

  return <ul className="list-none p-0!">{renderLevel(null, 0)}</ul>;
}

function isModuleDescendant(
  modules: CourseModule[],
  candidateId: string | undefined,
  ancestorId: string,
): boolean {
  let currentId = candidateId;
  const seen = new Set<string>();
  while (currentId && !seen.has(currentId)) {
    if (currentId === ancestorId) return true;
    seen.add(currentId);
    currentId =
      modules.find((item) => item.id === currentId)?.parent_id ?? undefined;
  }
  return false;
}

function nagSymbol(nag: number): string {
  return (
    {
      1: '!',
      2: '?',
      3: '!!',
      4: '??',
      5: '!?',
      6: '?!',
    }[nag] ?? String(nag)
  );
}
