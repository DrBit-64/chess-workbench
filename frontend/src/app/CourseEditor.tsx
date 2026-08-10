import {
  Alert,
  Button,
  Card,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { Chess } from 'chess.js';
import { useEffect, useMemo, useReducer, useState } from 'react';
import { Chessboard } from 'react-chessboard';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import useSWR from 'swr';

import { fetchJson, requestJson } from '../logic/api/client';
import type {
  Course,
  CitableSource,
  ContentHistory,
  CourseModule,
  ModuleEditor,
  Occurrence,
} from '../logic/api/types';
import {
  FAST_MOVE_ANIMATION_MS,
  lichessSquareStyles,
} from './boardInteraction';
import { createDraftState, editorDraftReducer } from './editorDraft';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

export function CourseEditor() {
  const { courseId = '' } = useParams();
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
  const [selectedSquare, setSelectedSquare] = useState<string>();
  const [uciInput, setUciInput] = useState('');
  const [moduleModal, setModuleModal] = useState(false);
  const [publishModal, setPublishModal] = useState(false);
  const [publishTarget, setPublishTarget] = useState<string>();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [readingMode, setReadingMode] = useState(true);
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
        modules.find((item) => item.id === requested)?.id ?? modules[0].id,
      );
    }
  }, [moduleId, modules, searchParams]);
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
  const path = useMemo(() => {
    const result: ModuleEditor['occurrences'] = [];
    const visited = new Set<string>();
    let node = current;
    while (node && !visited.has(node.id)) {
      visited.add(node.id);
      result.push(node);
      node = node.parent_id ? byId.get(node.parent_id) : undefined;
    }
    return result.reverse();
  }, [byId, current]);
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
  const notesById = useMemo(
    () => new Map((editor?.notes ?? []).map((item) => [item.id, item])),
    [editor?.notes],
  );
  const sourcesBySpanId = useMemo(
    () =>
      new Map(
        citableSources.map((item) => [item.source_span.id, item] as const),
      ),
    [citableSources],
  );
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
    const game = new Chess(current.full_fen);
    let move;
    try {
      move = game.move({ from: source, to: target, promotion: 'q' });
    } catch {
      return false;
    }
    if (!move) return false;
    const uci = `${source}${target}${move.promotion ?? ''}`;
    const existing = candidates.find((item) => item.inbound_uci === uci);
    if (existing) {
      selectOccurrence(existing.id);
      return true;
    }
    setPendingFen(game.fen());
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
        if (course?.mode === 'opening_explorer') {
          await mutateExplorerEditors();
        } else {
          await mutateModuleEditor();
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
    const game = new Chess(current.full_fen);
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

  function submitUciInput() {
    const normalized = uciInput.trim().toLowerCase();
    if (!/^[a-h][1-8][a-h][1-8]q?$/.test(normalized)) {
      void message.warning('请输入标准 UCI，例如 e2e4');
      return;
    }
    if (submitMove(normalized.slice(0, 2), normalized.slice(2, 4))) {
      setUciInput('');
    }
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
      <div className="editor-grid">
        <Card
          title={course.mode === 'opening_explorer' ? '探索概览' : '章节'}
          size="small"
          className="editor-panel"
        >
          {course.mode === 'opening_explorer' ? (
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
          ) : (
            <List
              dataSource={modules}
              locale={{ emptyText: '先创建一个章节' }}
              renderItem={(item) => (
                <List.Item
                  className={item.id === moduleId ? 'bg-emerald-50' : ''}
                >
                  <Button
                    type="text"
                    className="w-full text-left"
                    onClick={() => {
                      setModuleId(item.id);
                      setOccurrenceId(undefined);
                    }}
                  >
                    {item.parent_id ? '↳ ' : ''}
                    {item.title}
                  </Button>
                </List.Item>
              )}
            />
          )}
        </Card>
        <section className="min-w-0">
          {current ? (
            <>
              <div className="mx-auto max-w-[600px]">
                <Chessboard
                  id="course-editor-board"
                  position={pendingFen ?? current.full_fen}
                  animationDuration={FAST_MOVE_ANIMATION_MS}
                  onPieceDrop={onPieceDrop}
                  onPieceDragBegin={(_, source) => selectOwnPiece(source)}
                  onPieceDragEnd={() => setSelectedSquare(undefined)}
                  onSquareClick={onSquareClick}
                  autoPromoteToQueen
                  customSquareStyles={boardSquareStyles}
                  customBoardStyle={{
                    borderRadius: '8px',
                    boxShadow: '0 12px 30px rgba(28,25,23,.16)',
                  }}
                />
              </div>
              <div className="mx-auto mt-3 max-w-[600px]">
                <Space.Compact className="w-full">
                  <Input
                    aria-label="键盘输入着法 UCI"
                    placeholder="键盘落子，例如 e2e4"
                    value={uciInput}
                    onChange={(event) => setUciInput(event.target.value)}
                    onPressEnter={submitUciInput}
                  />
                  <Button onClick={submitUciInput}>提交着法</Button>
                </Space.Compact>
                <Typography.Text type="secondary" className="text-xs">
                  可拖动棋子、依次点选起止格，或输入 UCI 着法。
                </Typography.Text>
              </div>
              <div
                className="mt-4 flex flex-wrap items-center justify-center gap-2"
                aria-label="当前路径"
              >
                {path.map((item, index) => (
                  <Button
                    key={item.id}
                    size="small"
                    type={item.id === current.id ? 'primary' : 'default'}
                    onClick={() => selectOccurrence(item.id)}
                  >
                    {index === 0 ? '起点' : item.inbound_san}
                  </Button>
                ))}
              </div>
            </>
          ) : (
            <Empty description="选择带起始局面的章节" />
          )}
        </section>
        <Card
          title={course.mode === 'traditional' ? '章节正文' : '当前局面'}
          size="small"
          className="editor-panel reading-panel"
          extra={
            course.mode === 'traditional' ? (
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
            ) : transpositionCount > 1 ? (
              <Tag color="gold">转置 × {transpositionCount}</Tag>
            ) : null
          }
        >
          {course.mode === 'traditional' ? (
            <article className="chapter-reader" aria-label="章节正文">
              {!readingMode ? (
                <div className="mb-3 flex justify-end">
                  <Button size="small" onClick={() => setNarrativeModal(true)}>
                    添加叙述正文
                  </Button>
                </div>
              ) : null}
              {editor?.content_blocks.length ? (
                editor.content_blocks.map((block) => {
                  const embeddedNote = block.knowledge_note_id
                    ? notesById.get(block.knowledge_note_id)
                    : undefined;
                  const embeddedOccurrenceId =
                    embeddedNote?.target.kind === 'occurrence'
                      ? embeddedNote.target.occurrence_id
                      : undefined;
                  return (
                    <section
                      key={block.id}
                      className={`reader-block ${block.kind}`}
                    >
                      {block.kind === 'section_header' ? (
                        <Typography.Title level={4}>
                          {block.heading}
                        </Typography.Title>
                      ) : null}
                      {block.kind === 'narrative' && block.markdown ? (
                        <>
                          <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
                            {block.markdown}
                          </ReactMarkdown>
                          {(block.source_span_ids ?? []).length ? (
                            <Space size={[4, 4]} wrap>
                              {(block.source_span_ids ?? []).map((spanId) => (
                                <Tag key={spanId} color="blue">
                                  {sourceLabel(spanId)}
                                </Tag>
                              ))}
                            </Space>
                          ) : null}
                        </>
                      ) : null}
                      {block.kind === 'move_sequence' ? (
                        <Button
                          type="text"
                          className="reader-position-link"
                          onClick={() =>
                            block.root_occurrence_id
                              ? selectOccurrence(block.root_occurrence_id)
                              : undefined
                          }
                        >
                          ♟ 交互棋谱从这里开始
                        </Button>
                      ) : null}
                      {block.kind === 'knowledge_note' && embeddedNote ? (
                        <>
                          <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
                            {embeddedNote.rendered_markdown}
                          </ReactMarkdown>
                          <Space size={[4, 4]} wrap>
                            {embeddedNote.rendered_source_span_ids.map(
                              (spanId) => (
                                <Tag key={spanId} color="blue">
                                  {sourceLabel(spanId)}
                                </Tag>
                              ),
                            )}
                            {embeddedOccurrenceId ? (
                              <Button
                                size="small"
                                type="link"
                                onClick={() =>
                                  selectOccurrence(embeddedOccurrenceId)
                                }
                              >
                                查看关联局面
                              </Button>
                            ) : null}
                          </Space>
                        </>
                      ) : null}
                    </section>
                  );
                })
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="本章还没有正文"
                />
              )}
            </article>
          ) : null}
          {course.mode === 'traditional' ? <Divider /> : null}
          <div className="mb-2 flex items-center justify-between gap-2">
            <Typography.Text strong>当前局面</Typography.Text>
            {transpositionCount > 1 ? (
              <Tag color="gold">转置 × {transpositionCount}</Tag>
            ) : null}
          </div>
          <Typography.Text type="secondary">直接候选着</Typography.Text>
          <List
            className="mt-2"
            dataSource={candidates}
            locale={{ emptyText: '在棋盘走一步以创建候选着' }}
            renderItem={(item, index) => (
              <List.Item>
                <Button
                  className="w-full"
                  type={index === 0 ? 'primary' : 'default'}
                  onClick={() => selectOccurrence(item.id)}
                >
                  {item.inbound_san}
                  <span className="ml-2">{item.inbound_uci}</span>
                </Button>
              </List.Item>
            )}
          />
          {current ? (
            <Typography.Paragraph className="mt-4 break-all text-xs text-stone-500">
              {current.full_fen}
            </Typography.Paragraph>
          ) : null}
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
                    <Typography.Text type="secondary">安全预览</Typography.Text>
                    {draft.present.markdown ? (
                      <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
                        {draft.present.markdown}
                      </ReactMarkdown>
                    ) : (
                      <Typography.Paragraph type="secondary" className="mb-0!">
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
