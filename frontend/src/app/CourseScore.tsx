import type { MouseEvent as ReactMouseEvent, ReactNode } from 'react';
import { Fragment, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';

import type { ModuleEditor } from '../logic/api/types';
import {
  buildCourseScoreLayout,
  type CourseMoveRow,
  type CourseMoveView,
  type CourseOccurrence,
  type CourseVariation,
} from './courseMoveLayout';

type CourseNote = ModuleEditor['notes'][number];

interface CourseMenuState {
  x: number;
  y: number;
  title: string;
  pages: Array<{ spanId: string; page: number }>;
  occurrence?: CourseOccurrence;
}

export type CourseMoveAction =
  'promote_variation' | 'make_mainline' | 'set_nag' | 'delete_subtree';

export function CourseScore({
  occurrences,
  notes,
  rootId,
  currentId,
  sourcePageBySpanId,
  onSelectOccurrence,
  onSelectSource,
  onMoveAction,
}: {
  occurrences: CourseOccurrence[];
  notes: CourseNote[];
  rootId: string;
  currentId?: string;
  sourcePageBySpanId: ReadonlyMap<string, number>;
  onSelectOccurrence: (id: string) => void;
  onSelectSource: (spanId: string) => void;
  onMoveAction: (
    action: CourseMoveAction,
    occurrence: CourseOccurrence,
  ) => void;
}) {
  const layout = useMemo(
    () => buildCourseScoreLayout(occurrences, rootId),
    [occurrences, rootId],
  );
  const notesByOccurrence = useMemo(() => {
    const result = new Map<string, CourseNote[]>();
    for (const note of notes ?? []) {
      if (note.target.kind !== 'occurrence') continue;
      const entries = result.get(note.target.occurrence_id) ?? [];
      entries.push(note);
      result.set(note.target.occurrence_id, entries);
    }
    return result;
  }, [notes]);
  const [menu, setMenu] = useState<CourseMenuState | null>(null);

  function openNoteMenu(event: ReactMouseEvent, note: CourseNote) {
    event.preventDefault();
    const pages = note.rendered_source_span_ids.flatMap((spanId) => {
      const page = sourcePageBySpanId.get(spanId);
      return page === undefined ? [] : [{ spanId, page }];
    });
    if (pages[0]) onSelectSource(pages[0].spanId);
    setMenu({
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - 232)),
      y: Math.max(
        8,
        Math.min(event.clientY, window.innerHeight - 70 - pages.length * 34),
      ),
      title: '局面注释',
      pages,
    });
  }

  function openMoveMenu(event: ReactMouseEvent, occurrence: CourseOccurrence) {
    event.preventDefault();
    const sourceSpanIds = Array.isArray(occurrence.context?.source_span_ids)
      ? occurrence.context.source_span_ids.filter(
          (value): value is string => typeof value === 'string',
        )
      : [];
    const pages = sourceSpanIds.flatMap((spanId) => {
      const page = sourcePageBySpanId.get(spanId);
      return page === undefined ? [] : [{ spanId, page }];
    });
    if (pages[0]) onSelectSource(pages[0].spanId);
    setMenu({
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - 232)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - 280)),
      title: occurrence.inbound_san ?? occurrence.inbound_uci ?? '棋步',
      pages,
      occurrence,
    });
  }

  const rootNotes = notesByOccurrence.get(rootId) ?? [];
  return (
    <nav aria-label="课程棋谱" className="overflow-hidden bg-white">
      <button
        type="button"
        aria-current={currentId === rootId ? 'step' : undefined}
        onClick={() => onSelectOccurrence(rootId)}
        className={`w-full border-b border-stone-200 px-3 py-2 text-left text-sm ${
          currentId === rootId
            ? 'bg-emerald-800 text-white'
            : 'text-stone-600 hover:bg-stone-100'
        }`}
      >
        起始局面
      </button>
      <CourseNotes
        notes={rootNotes}
        onContextMenu={openNoteMenu}
        onSelectOccurrence={() => onSelectOccurrence(rootId)}
      />
      {layout.mainlineRows.length === 0 ? (
        <p className="px-3 py-6 text-center text-sm text-stone-500">
          在棋盘走一步以创建棋谱
        </p>
      ) : (
        layout.mainlineRows.map((row, index) => {
          const anchors = [
            ...(index === 0 ? [rootId] : []),
            row.white?.occurrence.id,
            row.black?.occurrence.id,
          ].filter((id): id is string => id !== undefined);
          const whiteNotes = row.white
            ? (notesByOccurrence.get(row.white.occurrence.id) ?? [])
            : [];
          const blackNotes = row.black
            ? (notesByOccurrence.get(row.black.occurrence.id) ?? [])
            : [];
          const splitPair = row.black !== null && whiteNotes.length > 0;
          return (
            <div key={row.key}>
              <MainlineRow
                row={splitPair ? { ...row, black: null } : row}
                currentId={currentId}
                onSelectOccurrence={onSelectOccurrence}
                onMoveContextMenu={openMoveMenu}
              />
              <CourseNotes
                notes={whiteNotes}
                onContextMenu={openNoteMenu}
                onSelectOccurrence={(note) => {
                  if (note.target.kind === 'occurrence') {
                    onSelectOccurrence(note.target.occurrence_id);
                  }
                }}
              />
              {splitPair ? (
                <MainlineRow
                  row={{ ...row, white: null }}
                  currentId={currentId}
                  onSelectOccurrence={onSelectOccurrence}
                  onMoveContextMenu={openMoveMenu}
                />
              ) : null}
              <CourseNotes
                notes={blackNotes}
                onContextMenu={openNoteMenu}
                onSelectOccurrence={(note) => {
                  if (note.target.kind === 'occurrence') {
                    onSelectOccurrence(note.target.occurrence_id);
                  }
                }}
              />
              {anchors.flatMap((anchor) =>
                (layout.variationsByParent.get(anchor) ?? []).map(
                  (variation) => (
                    <VariationLine
                      key={variation.key}
                      variation={variation}
                      variationsByParent={layout.variationsByParent}
                      notesByOccurrence={notesByOccurrence}
                      currentId={currentId}
                      onSelectOccurrence={onSelectOccurrence}
                      onNoteContextMenu={openNoteMenu}
                      onMoveContextMenu={openMoveMenu}
                    />
                  ),
                ),
              )}
            </div>
          );
        })
      )}
      <CourseContextMenu
        menu={menu}
        onSelectSource={onSelectSource}
        onMoveAction={onMoveAction}
        onClose={() => setMenu(null)}
      />
    </nav>
  );
}

export function CourseScoreControls({
  occurrences,
  rootId,
  currentId,
  onSelectOccurrence,
  recordMoves,
  onRecordMovesChange,
  boardOrientation,
  onFlipBoard,
}: {
  occurrences: CourseOccurrence[];
  rootId: string;
  currentId?: string;
  onSelectOccurrence: (id: string) => void;
  recordMoves: boolean;
  onRecordMovesChange: (enabled: boolean) => void;
  boardOrientation: 'white' | 'black';
  onFlipBoard: () => void;
}) {
  const occurrenceById = useMemo(
    () => new Map(occurrences.map((item) => [item.id, item] as const)),
    [occurrences],
  );
  const childrenByParent = useMemo(() => {
    const result = new Map<string, CourseOccurrence[]>();
    for (const occurrence of occurrences) {
      if (occurrence.parent_id === null) continue;
      const children = result.get(occurrence.parent_id) ?? [];
      children.push(occurrence);
      result.set(occurrence.parent_id, children);
    }
    for (const children of result.values()) {
      children.sort(
        (left, right) =>
          left.sort_order - right.sort_order || left.id.localeCompare(right.id),
      );
    }
    return result;
  }, [occurrences]);
  const activeOccurrence =
    occurrenceById.get(currentId ?? '') ?? occurrenceById.get(rootId);
  const previousId = activeOccurrence?.parent_id ?? undefined;
  const nextId = activeOccurrence
    ? childrenByParent.get(activeOccurrence.id)?.[0]?.id
    : undefined;
  let endId = activeOccurrence?.id ?? rootId;
  while (childrenByParent.get(endId)?.[0]) {
    endId = childrenByParent.get(endId)![0].id;
  }

  return (
    <div
      className="course-score-controls flex flex-wrap items-center justify-center gap-1 border-t border-stone-200 bg-stone-50 px-2 py-2"
      aria-label="棋谱导航与棋盘设置"
    >
      <ScoreControl
        label="回到开始"
        symbol="|◀"
        disabled={activeOccurrence?.id === rootId}
        onClick={() => onSelectOccurrence(rootId)}
      />
      <ScoreControl
        label="上一步"
        symbol="‹"
        disabled={!previousId}
        onClick={() => previousId && onSelectOccurrence(previousId)}
      />
      <ScoreControl
        label="下一步"
        symbol="›"
        disabled={!nextId}
        onClick={() => nextId && onSelectOccurrence(nextId)}
      />
      <ScoreControl
        label="前往主线末尾"
        symbol="▶|"
        disabled={activeOccurrence?.id === endId}
        onClick={() => onSelectOccurrence(endId)}
      />
      <span className="mx-1 h-6 border-l border-stone-300" />
      <label className="inline-flex cursor-pointer items-center gap-1.5 rounded px-2 py-1 text-xs text-stone-600 hover:bg-stone-100">
        <input
          type="checkbox"
          checked={recordMoves}
          onChange={(event) => onRecordMovesChange(event.target.checked)}
        />
        记录走棋
      </label>
      <ScoreControl
        label={`翻转棋盘（当前${boardOrientation === 'white' ? '白方' : '黑方'}视角）`}
        symbol="↕"
        onClick={onFlipBoard}
      />
    </div>
  );
}

function MainlineRow({
  row,
  currentId,
  onSelectOccurrence,
  onMoveContextMenu,
}: {
  row: CourseMoveRow;
  currentId?: string;
  onSelectOccurrence: (id: string) => void;
  onMoveContextMenu: (
    event: ReactMouseEvent,
    occurrence: CourseOccurrence,
  ) => void;
}) {
  return (
    <div className="grid min-h-9 grid-cols-[2.5rem_1fr_1fr] border-b border-stone-100">
      <span className="flex items-center justify-center bg-stone-50 font-mono text-xs text-stone-400">
        {row.white === null ? `${row.moveNumber}...` : `${row.moveNumber}.`}
      </span>
      <div className="border-l border-stone-100">
        {row.white ? (
          <CourseMove
            move={row.white}
            active={row.white.occurrence.id === currentId}
            onSelectOccurrence={onSelectOccurrence}
            onContextMenu={onMoveContextMenu}
            fullWidth
          />
        ) : null}
      </div>
      <div className="border-l border-stone-100">
        {row.black ? (
          <CourseMove
            move={row.black}
            active={row.black.occurrence.id === currentId}
            onSelectOccurrence={onSelectOccurrence}
            onContextMenu={onMoveContextMenu}
            fullWidth
          />
        ) : null}
      </div>
    </div>
  );
}

function VariationLine({
  variation,
  variationsByParent,
  notesByOccurrence,
  currentId,
  onSelectOccurrence,
  onNoteContextMenu,
  onMoveContextMenu,
}: {
  variation: CourseVariation;
  variationsByParent: ReadonlyMap<string, CourseVariation[]>;
  notesByOccurrence: ReadonlyMap<string, CourseNote[]>;
  currentId?: string;
  onSelectOccurrence: (id: string) => void;
  onNoteContextMenu: (event: ReactMouseEvent, note: CourseNote) => void;
  onMoveContextMenu: (
    event: ReactMouseEvent,
    occurrence: CourseOccurrence,
  ) => void;
}) {
  const visualDepth = Math.min(5, variation.depth);
  const parenthetical = variation.presentation === 'parenthetical';
  const moves = variation.moves.map((move, index) => (
    <Fragment key={move.occurrence.id}>
      <span className="inline-flex items-baseline gap-1">
        {(index === 0 || move.side === 'white') && (
          <span className="font-mono text-xs text-stone-400">
            {move.side === 'black'
              ? `${move.moveNumber}...`
              : `${move.moveNumber}.`}
          </span>
        )}
        <CourseMove
          move={move}
          active={move.occurrence.id === currentId}
          onSelectOccurrence={onSelectOccurrence}
          onContextMenu={onMoveContextMenu}
        />
      </span>
      {(notesByOccurrence.get(move.occurrence.id) ?? []).map((note) => (
        <span
          key={note.id}
          onContextMenu={(event) => onNoteContextMenu(event, note)}
          className="basis-full cursor-context-menu whitespace-normal py-0.5 italic text-stone-600"
        >
          <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
            {note.rendered_markdown}
          </ReactMarkdown>
        </span>
      ))}
      {(variationsByParent.get(move.occurrence.id) ?? []).map((nested) => (
        <VariationLine
          key={nested.key}
          variation={nested}
          variationsByParent={variationsByParent}
          notesByOccurrence={notesByOccurrence}
          currentId={currentId}
          onSelectOccurrence={onSelectOccurrence}
          onNoteContextMenu={onNoteContextMenu}
          onMoveContextMenu={onMoveContextMenu}
        />
      ))}
    </Fragment>
  ));

  if (parenthetical) {
    return (
      <span
        data-variation-depth={variation.depth}
        data-variation-path={variation.path.join('/')}
        data-variation-presentation="parenthetical"
        className="inline-flex flex-wrap items-baseline gap-x-1.5 italic text-stone-500"
      >
        <span aria-hidden="true">(</span>
        {moves}
        <span aria-hidden="true">)</span>
      </span>
    );
  }

  return (
    <div
      data-variation-depth={variation.depth}
      data-variation-path={variation.path.join('/')}
      data-variation-presentation="rail"
      style={{ paddingLeft: `${visualDepth * 14 + 8}px` }}
      className="relative basis-full py-1 pr-2 text-sm leading-6"
    >
      <BranchRails depth={visualDepth} />
      <div className="flex flex-wrap items-baseline gap-x-1.5">{moves}</div>
    </div>
  );
}

function CourseMove({
  move,
  active,
  onSelectOccurrence,
  onContextMenu,
  fullWidth = false,
}: {
  move: CourseMoveView;
  active: boolean;
  onSelectOccurrence: (id: string) => void;
  onContextMenu: (event: ReactMouseEvent, occurrence: CourseOccurrence) => void;
  fullWidth?: boolean;
}) {
  const occurrence = move.occurrence;
  const label = occurrence.inbound_san ?? occurrence.inbound_uci ?? '着法';
  return (
    <button
      type="button"
      aria-label={`${label} ${occurrence.inbound_uci ?? ''}`.trim()}
      aria-current={active ? 'step' : undefined}
      title={occurrence.inbound_uci ?? undefined}
      onClick={() => onSelectOccurrence(occurrence.id)}
      onContextMenu={(event) => onContextMenu(event, occurrence)}
      className={`${fullWidth ? 'flex h-full w-full' : 'inline-flex'} min-w-0 items-center rounded-sm px-2 py-1 text-left text-sm font-medium hover:bg-emerald-100 ${
        active ? 'bg-emerald-800 text-white hover:bg-emerald-800' : ''
      }`}
    >
      {label}
      {occurrence.nag !== null ? (
        <span className="ml-0.5 font-semibold text-amber-700">
          {nagLabel(occurrence.nag)}
        </span>
      ) : null}
    </button>
  );
}

function CourseNotes({
  notes,
  onContextMenu,
  onSelectOccurrence,
}: {
  notes: CourseNote[];
  onContextMenu: (event: ReactMouseEvent, note: CourseNote) => void;
  onSelectOccurrence: (note: CourseNote) => void;
}) {
  if (notes.length === 0) return null;
  return notes.map((note) => (
    <div
      key={note.id}
      role="button"
      tabIndex={0}
      onClick={() => onSelectOccurrence(note)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ')
          onSelectOccurrence(note);
      }}
      onContextMenu={(event) => onContextMenu(event, note)}
      className="cursor-context-menu border-b border-stone-100 px-3 py-1.5 text-sm italic leading-5 text-stone-700 hover:bg-stone-50"
    >
      <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
        {note.rendered_markdown}
      </ReactMarkdown>
    </div>
  ));
}

function BranchRails({ depth }: { depth: number }) {
  return (
    <span aria-hidden="true">
      {Array.from({ length: depth }, (_, index) => (
        <span
          key={index}
          data-course-branch-rail={index + 1}
          style={{ left: `${index * 14}px` }}
          className="absolute inset-y-0 border-l-2 border-stone-300"
        />
      ))}
      {depth > 0 ? (
        <span
          style={{ left: `${(depth - 1) * 14}px` }}
          className="absolute top-3 w-3 border-t-2 border-stone-300"
        />
      ) : null}
    </span>
  );
}

function CourseContextMenu({
  menu,
  onSelectSource,
  onMoveAction,
  onClose,
}: {
  menu: CourseMenuState | null;
  onSelectSource: (spanId: string) => void;
  onMoveAction: (
    action: CourseMoveAction,
    occurrence: CourseOccurrence,
  ) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    if (menu === null) return;
    const close = () => onClose();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('click', close);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('click', close);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [menu, onClose]);
  if (menu === null) return null;
  const applyMoveAction = (action: CourseMoveAction) => {
    if (!menu.occurrence) return;
    onMoveAction(action, menu.occurrence);
    onClose();
  };
  const sourceContent: ReactNode = menu.pages.length ? (
    menu.pages.map((page) => (
      <button
        key={page.spanId}
        type="button"
        role="menuitem"
        onClick={() => {
          onSelectSource(page.spanId);
          onClose();
        }}
        className="block w-full px-3 py-1.5 text-left text-stone-700 hover:bg-stone-100"
      >
        来源：第 {page.page} 页
      </button>
    ))
  ) : (
    <p className="px-3 py-1.5 text-stone-400">没有可预览的 PDF 来源</p>
  );
  return (
    <div
      role="menu"
      aria-label={`${menu.title} 操作菜单`}
      style={{ left: menu.x, top: menu.y }}
      onClick={(event) => event.stopPropagation()}
      className="fixed z-50 w-56 overflow-hidden rounded-md border border-stone-300 bg-white py-1 text-sm shadow-xl"
    >
      <p className="border-b border-stone-100 px-3 py-1.5 font-semibold">
        {menu.title}
      </p>
      {menu.occurrence ? (
        <>
          <MenuAction
            label="提升变招"
            disabled={menu.occurrence.sort_order === 0}
            onClick={() => applyMoveAction('promote_variation')}
          />
          <MenuAction
            label="设为主线"
            onClick={() => applyMoveAction('make_mainline')}
          />
          <MenuAction
            label="招法评注"
            onClick={() => applyMoveAction('set_nag')}
          />
          <MenuAction
            label="从此处开始删除"
            danger
            onClick={() => applyMoveAction('delete_subtree')}
          />
          <div className="my-1 border-t border-stone-100" />
        </>
      ) : null}
      {sourceContent}
    </div>
  );
}

function MenuAction({
  label,
  disabled = false,
  danger = false,
  onClick,
}: {
  label: string;
  disabled?: boolean;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className={`block w-full px-3 py-1.5 text-left disabled:cursor-not-allowed disabled:text-stone-300 ${
        danger
          ? 'text-red-700 hover:bg-red-50'
          : 'text-stone-700 hover:bg-stone-100'
      }`}
    >
      {label}
    </button>
  );
}

function ScoreControl({
  label,
  symbol,
  disabled = false,
  onClick,
}: {
  label: string;
  symbol: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-8 min-w-9 place-items-center rounded px-2 text-lg font-semibold text-stone-600 hover:bg-stone-200 disabled:text-stone-300"
    >
      {symbol}
    </button>
  );
}

function nagLabel(nag: number): string {
  return (
    {
      1: '!',
      2: '?',
      3: '!!',
      4: '??',
      5: '!?',
      6: '?!',
    }[nag] ?? `$${nag}`
  );
}
