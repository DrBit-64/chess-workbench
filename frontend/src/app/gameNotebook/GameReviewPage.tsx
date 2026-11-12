import { Alert, Button, Dropdown, Spin } from 'antd';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import useSWR, { useSWRConfig } from 'swr';

import { ReaderFullscreenButton } from '../../components/ReaderFullscreenButton';
import { WorkbenchBoard } from '../../components/WorkbenchBoard';
import { useCompactReaderViewport } from '../../components/useCompactReaderViewport';
import {
  fetchJson,
  requestEmpty,
  requestJson,
  ApiError,
} from '../../logic/api/client';
import { CourseEvaluationBar } from '../CourseEvaluationBar';
import { lichessSquareStyles } from '../boardInteraction';
import { BookmarkEditor, type BookmarkFields } from './BookmarkEditor';
import { positionLabel } from './positionLabel';
import { ReviewPositionNotes, ReviewGameInfo } from './ReviewDetails';
import { GameReviewScore, type NotebookMoveAction } from './GameReviewScore';
import {
  useReviewBoardMoves,
  type ReviewDirection,
} from './useReviewBoardMoves';
import { PromotionDialog } from './PromotionDialog';
import { useGameClocks } from './GameClocks';
import {
  indexReviewTree,
  mergeTreeUpdate,
  type MoveUpdate,
} from './reviewTree';
import { ReviewNoteEditor, type ReviewNoteTarget } from './ReviewNoteEditor';
import {
  moveLabel,
  type ReviewBookmark,
  type ReviewBookmarks,
  type ReviewGame,
  type ReviewGameSummary,
  type ReviewNode,
} from './reviewTypes';
import { useGameReviewEngine } from './useGameReviewEngine';
import { GameReviewEnginePanel } from './GameReviewEnginePanel';
import './gameReview.css';

const base = '/api/notebook';
type Panel = 'score' | 'notes' | 'game';
const panels: ReadonlyArray<[Panel, string]> = [
  ['score', '棋谱'],
  ['notes', '评语与收藏'],
  ['game', '对局信息'],
];

export function GameReviewPage() {
  const { gameId } = useParams<{ gameId: string }>();
  const url = gameId ? `${base}/games/${gameId}` : null;
  const {
    data: game,
    error,
    mutate,
  } = useSWR<ReviewGame>(url, fetchJson, { revalidateOnFocus: true });
  if (error && !game)
    return (
      <section className="game-review-loading">
        <Alert
          type="error"
          title={
            error instanceof ApiError && error.status === 404
              ? '找不到这盘棋，可能已经删除。'
              : '棋谱读取失败，请重试。'
          }
        />
        <Button onClick={() => void mutate()}>重试</Button>
        <Link to="/games">返回我的对局</Link>
      </section>
    );
  if (!game || !url)
    return (
      <div className="game-review-loading">
        <Spin />
        正在读取棋谱…
      </div>
    );
  return (
    <GameReview
      key={game.id}
      game={game}
      url={url}
      updateGame={(next) => mutate(next, { revalidate: false })}
      reload={() => mutate()}
    />
  );
}

function GameReview({
  game,
  url,
  updateGame,
  reload,
}: {
  game: ReviewGame;
  url: string;
  updateGame: (
    next: (previous?: ReviewGame) => ReviewGame | undefined,
  ) => Promise<ReviewGame | undefined>;
  reload: () => Promise<ReviewGame | undefined>;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const [search, setSearch] = useSearchParams();
  const compact = useCompactReaderViewport({ compactInWideFullscreen: false });
  const { mutate: refresh } = useSWRConfig();
  const [panel, setPanel] = useState<Panel>('score');
  const [orientation, setOrientation] = useState<'white' | 'black'>('white');
  const [noteEditor, setNoteEditor] = useState<ReviewNoteTarget>();
  const [bookmarkEditor, setBookmarkEditor] = useState<ReviewBookmark>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; error?: boolean }>();
  const preferredNext = useRef(new Map<string, string>());
  const selectionToken = useRef<symbol>();
  const editingLock = useRef(false);
  const bookmarkUrl = `${base}/bookmarks?game_id=${game.id}`;
  const {
    data: bookmarks,
    error: bookmarkError,
    mutate: updateBookmarks,
  } = useSWR<ReviewBookmarks>(bookmarkUrl, fetchJson, {
    revalidateOnFocus: true,
  });
  const { data: suggestions } = useSWR<{ tags: string[] }>(
    bookmarkEditor ? `${base}/bookmark-tags` : null,
    fetchJson,
  );
  const tree = useMemo(() => indexReviewTree(game.nodes), [game.nodes]);
  const starred = useMemo(
    () => new Map((bookmarks?.items ?? []).map((item) => [item.node_id, item])),
    [bookmarks],
  );
  const requested = search.get('node');
  const node = requested ? tree.byId.get(requested) : tree.root;
  const bookmark = node && starred.get(node.id);
  const board = useReviewBoardMoves(
    node,
    tree.children,
    busy,
    select,
    (parent, uci) => editTree('move', parent, uci),
  );
  const analysis = useGameReviewEngine(game, node, board.fen);
  const clocks = useGameClocks(game, board.temporary ? undefined : node);
  const displayedNode = useRef(node?.id);
  useLayoutEffect(() => {
    displayedNode.current = node?.id;
    return () => {
      displayedNode.current = undefined;
      selectionToken.current = Symbol();
    };
  }, [node?.id]);

  function select(next: ReviewNode) {
    selectionToken.current = Symbol();
    board.reset();
    setNotice(undefined);
    if (node?.parent_id === next.id)
      preferredNext.current.set(next.id, node.id);
    let descendant: ReviewNode | undefined = next;
    while (descendant?.parent_id) {
      preferredNext.current.set(descendant.parent_id, descendant.id);
      descendant = tree.byId.get(descendant.parent_id);
    }
    const params = new URLSearchParams(search);
    params.set('node', next.id);
    setSearch(params, {
      replace: true,
      state: location.state,
      preventScrollReset: true,
    });
  }

  function nextFor(current: ReviewNode) {
    const remembered = preferredNext.current.get(current.id);
    const children = tree.children.get(current.id);
    return children?.find((child) => child.id === remembered) ?? children?.[0];
  }

  function step(direction: ReviewDirection) {
    if (!node || board.step(direction)) return;
    let destination: ReviewNode | undefined;
    if (direction === 'first') destination = tree.root;
    if (direction === 'previous' && node.parent_id)
      destination = tree.byId.get(node.parent_id);
    if (direction === 'next') destination = nextFor(node);
    if (direction === 'last') {
      destination = node;
      let next = nextFor(destination);
      while (next) {
        destination = next;
        next = nextFor(destination);
      }
    }
    if (destination && (destination !== node || board.temporary))
      select(destination);
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (
        event.defaultPrevented ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        noteEditor ||
        bookmarkEditor ||
        document.querySelector(
          'dialog[open], [role="dialog"], .nb-move-menu, .ant-dropdown:not(.ant-dropdown-hidden), .ant-popover:not(.ant-popover-hidden)',
        )
      )
        return;
      const el = event.target instanceof HTMLElement ? event.target : null;
      if (
        el?.closest(
          'textarea,input,select,[contenteditable="true"],[role="textbox"]',
        )
      )
        return;
      switch (event.key) {
        case 'ArrowLeft':
          event.preventDefault();
          step('previous');
          break;
        case 'ArrowRight':
          event.preventDefault();
          step('next');
          break;
        case 'Home':
          event.preventDefault();
          step('first');
          break;
        case 'End':
          event.preventDefault();
          step('last');
          break;
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  function backToLibrary() {
    if (location.state?.notebookBack) void navigate(-1);
    else void navigate('/games');
  }

  async function editTree(
    action: NotebookMoveAction | 'move',
    target: ReviewNode,
    uci?: string,
  ) {
    if (busy || editingLock.current) return;
    const startedAt = selectionToken.current;
    editingLock.current = true;
    setBusy(true);
    setNotice(undefined);
    try {
      const change = await requestJson<MoveUpdate>(
        action === 'move' ? url + '/moves' : `${url}/nodes/${target.id}/branch`,
        {
          method: 'POST',
          body: JSON.stringify({
            expected_version: game.version,
            ...(action === 'move'
              ? { parent_id: target.id, uci }
              : { kind: action }),
          }),
        },
      );
      const updated = await updateGame((previous) =>
        mergeTreeUpdate(previous, change),
      );
      const next = updated?.nodes.find((n) => n.id === change.selected_id);
      if (action !== 'move') {
        for (const changed of change.nodes) {
          if (changed.parent_id)
            preferredNext.current.delete(changed.parent_id);
        }
      }
      const removedCurrent =
        action === 'delete_subtree' &&
        change.nodes.some((n) => n.id === displayedNode.current && n.hidden);
      if (
        next &&
        (removedCurrent ||
          (action !== 'delete_subtree' && startedAt === selectionToken.current))
      ) {
        select(next);
      }
      if (action === 'delete_subtree') {
        setNotice({ text: '已从复盘棋谱中移除这条变化。' });
      } else if (action === 'restore_path') {
        setNotice({ text: '已恢复这条线路。' });
      }
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        await reload().catch(() => undefined);
        setNotice({
          text: '棋谱已在其他窗口修改。请核对最新棋谱后重试。',
          error: true,
        });
      } else {
        setNotice({ text: errorText(reason), error: true });
      }
    } finally {
      editingLock.current = false;
      setBusy(false);
    }
  }

  async function manageGame(action: 'archive' | 'restore' | 'delete') {
    if (busy) return;
    setBusy(true);
    try {
      if (action === 'delete') {
        await requestEmpty(`${url}?expected_version=${game.version}`, {
          method: 'DELETE',
        });
        void navigate('/games?archived=1', { replace: true });
      } else {
        const row = await requestJson<ReviewGameSummary>(url, {
          method: 'PATCH',
          body: JSON.stringify({
            expected_version: game.version,
            archived: action === 'archive',
          }),
        });
        await updateGame((previous) =>
          previous && previous.version <= row.version
            ? { ...previous, ...row }
            : previous,
        );
        setNotice({
          text:
            action === 'archive' ? '棋谱已归档，可在此恢复。' : '棋谱已恢复。',
        });
      }
      void refresh(
        (key) =>
          typeof key === 'string' &&
          (key.startsWith(base + '/game-catalog') ||
            key.split('?')[0] === base + '/games' ||
            key.startsWith(base + '/bookmarks') ||
            key === base + '/bookmark-tags'),
      );
    } catch (reason) {
      setNotice({ text: errorText(reason), error: true });
      void reload();
    } finally {
      setBusy(false);
    }
  }

  async function remember(row: ReviewBookmark) {
    await updateBookmarks(
      (previous) => {
        if (!previous) return previous;
        const items = previous.items.filter((b) => b.id !== row.id);
        if (row.active) items.unshift(row);
        return { ...previous, items, total: items.length };
      },
      { revalidate: false },
    );
    void refresh(
      (key) =>
        typeof key === 'string' &&
        key !== bookmarkUrl &&
        (key.startsWith(base + '/bookmarks') ||
          key === base + '/bookmark-tags'),
    );
  }

  async function star(action: 'current' | 'before' | 'relate' = 'current') {
    if (!node || board.temporary || busy) return;
    if (action === 'current' && bookmark) {
      setBookmarkEditor(bookmark);
      return;
    }
    const anchor =
      action === 'before' && node.parent_id
        ? tree.byId.get(node.parent_id)
        : node;
    if (!anchor) return;
    setBusy(true);
    try {
      const row = await requestJson<ReviewBookmark>(base + '/bookmarks', {
        method: 'POST',
        body: JSON.stringify({
          node_id: anchor.id,
          related_node_id: node.san ? node.id : null,
        }),
      });
      await remember(row);
      if (action === 'before' && displayedNode.current === node.id) {
        select(anchor);
        setPanel('notes');
      }
      setNotice({
        text:
          action === 'relate'
            ? `已关联 ${moveLabel(node)} 的棋步评语。`
            : `已收藏 · ${positionLabel(anchor)}`,
      });
    } catch (reason) {
      setNotice({ text: errorText(reason), error: true });
    } finally {
      setBusy(false);
    }
  }

  async function unstar(permanent: boolean) {
    if (!bookmark || busy) return;
    setBusy(true);
    try {
      if (permanent) {
        await requestEmpty(
          `${base}/bookmarks/${bookmark.id}?expected_version=${bookmark.version}`,
          { method: 'DELETE' },
        );
        await remember({ ...bookmark, active: false });
      } else {
        const row = await requestJson<ReviewBookmark>(
          `${base}/bookmarks/${bookmark.id}`,
          {
            method: 'PATCH',
            body: JSON.stringify({
              expected_version: bookmark.version,
              active: false,
            }),
          },
        );
        await remember(row);
      }
      setNotice({
        text: permanent
          ? '已删除局面收藏和收藏笔记。'
          : '已取消收藏。再次收藏此处可恢复笔记和标签。',
      });
    } catch (reason) {
      setNotice({ text: errorText(reason), error: true });
      void updateBookmarks();
    } finally {
      setBusy(false);
    }
  }

  function editNote(kind: 'move' | 'summary') {
    if (!node || (kind === 'move' && board.temporary)) return;
    setNoteEditor(
      kind === 'summary'
        ? {
            kind,
            text: game.summary,
            version: game.version,
            position: `${game.white} — ${game.black}`,
          }
        : {
            kind,
            nodeId: node.id,
            text: node.note,
            version: node.version,
            position: `${moveLabel(node)} · ${node.is_mainline ? '实战主线' : '分析变例'}`,
          },
    );
  }

  async function saveNote(text: string, version: number) {
    if (!noteEditor) return;
    if (noteEditor.kind === 'summary') {
      const summary = await requestJson<ReviewGameSummary>(url, {
        method: 'PATCH',
        body: JSON.stringify({ expected_version: version, summary: text }),
      });
      await updateGame((previous) =>
        previous && previous.version <= summary.version
          ? { ...previous, ...summary }
          : previous,
      );
    } else {
      const changed = await requestJson<ReviewNode>(
        `${url}/nodes/${noteEditor.nodeId}`,
        {
          method: 'PATCH',
          body: JSON.stringify({ expected_version: version, note: text }),
        },
      );
      await updateGame(
        (previous) =>
          previous && {
            ...previous,
            nodes: previous.nodes.map((n) =>
              n.id === changed.id && n.version <= changed.version
                ? { ...n, note: changed.note, version: changed.version }
                : n,
            ),
          },
      );
      void updateBookmarks();
    }
    void refresh(
      (key) =>
        typeof key === 'string' &&
        ((key.startsWith(base + '/bookmarks') && key !== bookmarkUrl) ||
          key.split('?')[0] === base + '/games' ||
          key.startsWith(base + '/game-catalog')),
    );
    setNotice({ text: text.trim() ? '笔记已保存。' : '笔记已删除。' });
  }

  async function saveBookmark(fields: BookmarkFields) {
    if (!bookmarkEditor) return;
    try {
      const changed = await requestJson<ReviewBookmark>(
        `${base}/bookmarks/${bookmarkEditor.id}`,
        {
          method: 'PATCH',
          body: JSON.stringify({
            ...fields,
            expected_version: bookmarkEditor.version,
          }),
        },
      );
      await remember(changed);
      setNotice({ text: '局面笔记已保存。' });
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        const latest = (await updateBookmarks())?.items.find(
          (b) => b.id === bookmarkEditor.id,
        );
        if (latest) setBookmarkEditor(latest);
        throw new Error('局面笔记已在其他设备修改。请核对最新记录后再保存。');
      }
      throw reason;
    }
  }

  if (!node || !tree.root) {
    return (
      <section className="game-review-loading">
        <Alert
          type="warning"
          title={
            requested ? '这个棋步已不存在。' : '这盘棋没有可显示的起始局面。'
          }
        />
        {tree.root && (
          <Button onClick={() => select(tree.root!)}>回到起始局面</Button>
        )}
        <Button onClick={backToLibrary}>返回我的对局</Button>
      </section>
    );
  }
  const previousPath = location.state?.notebookBack;
  const backLabel =
    typeof previousPath === 'string' &&
    /^\/games\/[^/?]+\?node=/.test(previousPath)
      ? '返回原局面'
      : '返回列表';
  const selectedNotes =
    !board.temporary &&
    Boolean(
      node.note || bookmark?.note || node.comment || node.starting_comment,
    );
  const canStepBack = Boolean(board.temporary || node.parent_id);
  const canStepForward = board.trial
    ? board.trial.cursor < board.trial.moves.length
    : Boolean(nextFor(node));
  const feedback = (
    <>
      {bookmarkError && (
        <Alert
          type="error"
          title="无法载入收藏"
          action={
            <Button size="small" onClick={() => void updateBookmarks()}>
              重试
            </Button>
          }
        />
      )}
      {notice && (
        <div
          role={notice.error ? 'alert' : 'status'}
          className={'game-review-feedback' + (notice.error ? ' error' : '')}
        >
          <span>{notice.text}</span>
          <button
            type="button"
            aria-label="关闭提示"
            onClick={() => setNotice(undefined)}
          >
            ×
          </button>
        </div>
      )}
    </>
  );
  return (
    <section
      className="game-review"
      data-compact={compact}
      data-selected-node={node.id}
      data-panel={panel}
    >
      <div className="game-review-board-column">
        <div className="game-review-board-pane" aria-label="复盘棋盘">
          <div className="game-review-board-frame course-board-with-evaluation">
            <WorkbenchBoard
              id="notebook-game-board"
              fitReaderPane={compact}
              position={board.fen ?? node.fen}
              playerClocks={clocks}
              boardOrientation={orientation}
              customArrows={analysis.live.arrows}
              evaluationBar={
                <CourseEvaluationBar
                  line={analysis.currentLine}
                  outcome={analysis.live.outcome}
                  orientation={orientation}
                />
              }
              arePiecesDraggable={board.enabled}
              onSquareClick={board.click}
              onPieceDrop={(from, to) => board.play(from, to)}
              customSquareStyles={lichessSquareStyles(
                board.fen ?? node.fen,
                board.selected,
                board.lastMove,
              )}
            />
          </div>
        </div>
        <nav className="game-review-controls" aria-label="棋盘操作">
          <button
            type="button"
            className="game-review-tool"
            onClick={backToLibrary}
            title={backLabel}
            aria-label={backLabel}
          >
            <svg
              aria-hidden="true"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M10 5 3 12l7 7 M3 12h16" />
            </svg>
          </button>
          <button
            type="button"
            className="game-review-tool"
            disabled={!canStepBack}
            onClick={() => step('previous')}
            title="上一步（←）"
            aria-label="上一步"
          >
            <svg
              aria-hidden="true"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="m15 5-7 7 7 7" />
            </svg>
          </button>
          <button
            type="button"
            className="game-review-tool"
            disabled={!canStepForward}
            onClick={() => step('next')}
            title="下一步（→）"
            aria-label="下一步"
          >
            <svg
              aria-hidden="true"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="m9 5 7 7-7 7" />
            </svg>
          </button>
          {board.temporary ? (
            <button
              type="button"
              className="game-review-star"
              onClick={() => select(node)}
              disabled={board.pending}
              title={
                board.pending ? '正在保存棋步' : '结束试走并回到棋谱所选局面'
              }
            >
              {board.pending ? '保存中…' : '结束试走'}
            </button>
          ) : (
            <button
              type="button"
              className="game-review-star"
              aria-pressed={Boolean(bookmark)}
              aria-label={bookmark ? '编辑局面收藏' : '收藏当前局面'}
              title={bookmark ? '编辑局面收藏' : '收藏当前局面'}
              disabled={busy || !bookmarks}
              onClick={() => void star()}
            >
              <span aria-hidden="true">{bookmark ? '★' : '☆'}</span>{' '}
              {bookmark ? '已收藏' : '收藏'}
            </button>
          )}
          <Dropdown
            trigger={['click']}
            menu={{
              items: [
                {
                  key: 'note',
                  label: node.note ? '编辑棋步评语' : '写棋步评语',
                  disabled: !node.san || board.temporary,
                  onClick: () => editNote('move'),
                },
                {
                  key: 'before',
                  label: '收藏走这步之前',
                  disabled:
                    !node.parent_id || board.temporary || busy || !bookmarks,
                  onClick: () => void star('before'),
                },
                ...(!board.temporary &&
                node.san &&
                bookmark &&
                !bookmark.related_moves.some((move) => move.node_id === node.id)
                  ? [
                      {
                        key: 'relate',
                        label: '关联刚走的棋步',
                        disabled: busy,
                        onClick: () => void star('relate'),
                      },
                    ]
                  : []),
                { type: 'divider' },
                {
                  key: 'first',
                  label: '起始局面',
                  disabled: !canStepBack,
                  onClick: () => step('first'),
                },
                {
                  key: 'last',
                  label: '最后一步',
                  disabled: !canStepForward,
                  onClick: () => step('last'),
                },
                {
                  key: 'flip',
                  label: '翻转棋盘',
                  onClick: () =>
                    setOrientation(orientation === 'white' ? 'black' : 'white'),
                },
              ],
            }}
          >
            <button
              type="button"
              className="game-review-tool"
              aria-label="棋步菜单"
              title="棋步菜单"
            >
              •••
            </button>
          </Dropdown>
          <ReaderFullscreenButton />
        </nav>
      </div>
      <div className="game-review-inspector">
        <div className="game-review-tabs" aria-label="复盘面板">
          {panels.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-label={label}
              aria-pressed={panel === id}
              onClick={() => setPanel(id)}
            >
              {label}
              {id === 'notes' && selectedNotes ? ' •' : ''}
            </button>
          ))}
        </div>
        {compact && feedback}
        <section
          className="game-review-score-column"
          data-active={panel === 'score'}
          aria-label="棋谱面板"
        >
          <GameReviewEnginePanel
            analysis={analysis}
            recording={board.recording}
            onRecordingChange={board.setRecordingMode}
            editingBusy={busy}
          />
          <GameReviewScore
            nodes={game.nodes}
            visible={!compact || panel === 'score'}
            root={tree.root}
            selectedId={node.id}
            bookmarks={starred}
            evaluations={analysis.scores}
            editingBusy={busy}
            onMoveAction={editTree}
            onSelect={select}
          />
        </section>
        <aside
          className="game-review-sidebar"
          aria-label="收藏与笔记"
          data-active={panel !== 'score'}
        >
          <header className="game-review-heading">
            <h1>
              {game.white} <span>—</span> {game.black}
            </h1>
            <p>
              {[game.result, game.date, game.archived_at ? '已归档' : null]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </header>
          {!compact && feedback}
          {board.temporary ? (
            <section
              className="game-review-sheet game-review-notes"
              data-active={panel === 'notes'}
              aria-label="评语与收藏面板"
            >
              <h2>{board.pending ? '正在记录棋步' : '试走局面'}</h2>
              {!board.pending && (
                <p>
                  回到棋谱并开启“记录走棋”，即可保存变化、添加评语或收藏局面。
                </p>
              )}
            </section>
          ) : (
            <ReviewPositionNotes
              key={node.id}
              active={panel === 'notes'}
              node={node}
              byId={tree.byId}
              bookmark={bookmark}
              busy={busy || !bookmarks}
              star={() => void star()}
              unstar={unstar}
              editNote={() => editNote('move')}
              editBookmark={setBookmarkEditor}
              select={select}
            />
          )}
          <ReviewGameInfo
            active={panel === 'game'}
            game={game}
            url={url}
            editSummary={() => editNote('summary')}
            busy={busy}
            manageGame={manageGame}
          />
        </aside>
      </div>
      {board.promotion && (
        <PromotionDialog
          onClose={board.cancelPromotion}
          onChoose={(piece) => {
            if (board.promotion)
              board.play(board.promotion.from, board.promotion.to, piece);
          }}
        />
      )}
      {noteEditor && (
        <ReviewNoteEditor
          target={noteEditor}
          onClose={() => setNoteEditor(undefined)}
          onSave={saveNote}
          reload={async () => {
            const latest = await reload();
            if (!latest) return;
            if (noteEditor.kind === 'summary')
              return { text: latest.summary, version: latest.version };
            const changed = latest.nodes.find(
              (n) => n.id === noteEditor.nodeId,
            );
            return changed && { text: changed.note, version: changed.version };
          }}
        />
      )}
      {bookmarkEditor && (
        <BookmarkEditor
          initial={{
            title: bookmarkEditor.title,
            note: bookmarkEditor.note,
            tags: bookmarkEditor.tags,
          }}
          suggestedTags={suggestions?.tags ?? []}
          onSave={saveBookmark}
          onClose={() => setBookmarkEditor(undefined)}
        />
      )}
    </section>
  );
}

function errorText(reason: unknown) {
  return reason instanceof Error ? reason.message : '保存失败，请重试。';
}

export default GameReviewPage;
