import { Button, Input, Alert, Spin } from 'antd';
import type { Square } from 'chess.js';
import { useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import useSWR from 'swr';
import { ReaderFullscreenButton } from '../../components/ReaderFullscreenButton';
import { WorkbenchBoard } from '../../components/WorkbenchBoard';
import {
  ApiError,
  fetchJson,
  requestJson,
  requestEmpty,
} from '../../logic/api/client';
import type { paths } from '../../types/api.generated';
import {
  FAST_MOVE_ANIMATION_MS,
  lichessSquareStyles,
} from '../boardInteraction';
import { NotebookDialog } from './NotebookDialog';
import { notebookApi, type SavedBookmark } from './catalogApi';
import {
  advanceAnswer,
  lineNotation,
  parseAnswerLines,
  positionAfter,
} from './practiceLines';
import type { ReviewGame } from './reviewTypes';
import { positionLabel } from './positionLabel';
import './notebookPractice.css';

type Definition =
  paths['/api/notebook/bookmarks/{bookmark_id}/practice']['get']['responses'][200]['content']['application/json'];

export default function BookmarkPractice() {
  const { bookmarkId } = useParams();
  const url = notebookApi + '/bookmarks/' + bookmarkId;
  const bookmark = useSWR<SavedBookmark>(url, fetchJson);
  const practice = useSWR<Definition>(url + '/practice', fetchJson);
  const location = useLocation();
  const navigate = useNavigate();
  const back = location.state?.notebookBack;
  return (
    <section className="nb-practice" aria-label="局面练习">
      <header>
        {typeof back === 'string' ? (
          <Button onClick={() => navigate(-1)}>返回</Button>
        ) : (
          <Link to="/games/positions">局面收藏</Link>
        )}
        <h1>练习局面</h1>
        <ReaderFullscreenButton />
      </header>
      {bookmark.error || practice.error ? (
        <Alert
          type="error"
          showIcon
          title="无法读取此局面或练习"
          action={
            <Button
              onClick={() => {
                void bookmark.mutate();
                void practice.mutate();
              }}
            >
              重试
            </Button>
          }
        />
      ) : bookmark.data && practice.data ? (
        <Exercise
          key={bookmark.data.id}
          bookmark={bookmark.data}
          definition={practice.data}
          reload={practice.mutate}
        />
      ) : (
        <Spin aria-label="正在载入练习" />
      )}
    </section>
  );
}

function Exercise({
  bookmark,
  definition,
  reload,
}: {
  bookmark: SavedBookmark;
  definition: Definition;
  reload: (data?: Definition) => Promise<Definition | undefined>;
}) {
  const fen = bookmark.fen;
  const url = notebookApi + '/bookmarks/' + bookmark.id + '/practice';
  const [editing, setEditing] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [notation, setNotation] = useState('');
  const [editVersion, setEditVersion] = useState(0);
  const [recording, setRecording] = useState(false);
  const [played, setPlayed] = useState<string[]>([]);
  const [recorded, setRecorded] = useState<string[]>([]);
  const [selected, setSelected] = useState<Square>();
  const [promotion, setPromotion] = useState<{ from: Square; to: Square }>();
  const [finished, setFinished] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<number>();
  const [conflict, setConflict] = useState<Definition>();
  const { data: game } = useSWR<ReviewGame>(
    editing ? notebookApi + '/games/' + bookmark.game_id : null,
    fetchJson,
  );
  const moves = recording ? recorded : played;
  const board = positionAfter(fen, moves);
  const enabled =
    !busy &&
    (recording ||
      (!editing && !finished && !revealed && definition.lines.length > 0));
  const startSide = fen.split(' ')[1] === 'w' ? 'white' : 'black';

  function restart() {
    setPlayed([]);
    setSelected(undefined);
    setPromotion(undefined);
    setRevealed(false);
    setFinished(false);
    setFeedback('');
    setError('');
  }
  function edit() {
    restart();
    setEditing(true);
    setRecording(false);
    setEditVersion(definition.version);
    setConflict(undefined);
    setPrompt(definition.prompt);
    setNotation(
      definition.lines.map((line) => lineNotation(fen, line)).join('\n'),
    );
  }
  function submitMove(from: Square, to: Square, piece?: string) {
    if (!enabled) return false;
    const legal = board
      .moves({ square: from, verbose: true })
      .filter((move) => move.to === to);
    if (!legal.length) return false;
    if (legal.some((move) => move.promotion) && !piece) {
      setPromotion({ from, to });
      return false;
    }
    setSelected(undefined);
    setPromotion(undefined);
    const chosen = legal.find((move) => move.promotion === piece);
    if (!chosen) return false;
    const uci = from + to + (chosen.promotion ?? '');
    if (recording) {
      setRecorded([...recorded, uci]);
      return true;
    }
    const next = advanceAnswer(definition.lines, played, uci);
    if (!next) {
      setFeedback(
        `${chosen.san} 是合法走法，没有列入这道题的答案。可以再试一次。`,
      );
      return false;
    }
    setPlayed(next.moves);
    setFinished(next.finished);
    setFeedback(next.finished ? '已完成这条变化。' : '走法正确，轮到你继续。');
    return true;
  }
  function clickSquare(square: Square) {
    if (!enabled) return;
    if (board.get(square)?.color === board.turn()) {
      setSelected(square === selected ? undefined : square);
    } else if (selected) {
      submitMove(selected, square);
    }
  }
  function appendLine(line: string) {
    setNotation((previous) =>
      [previous.trimEnd(), line].filter(Boolean).join('\n'),
    );
  }
  function sourceLine() {
    if (!game) return [];
    const nodes = new Map(
      game.nodes
        .filter((n) => n.parent_id && n.sort_order === 0)
        .map((n) => [n.parent_id, n]),
    );
    const result: string[] = [];
    // When a decision was collected from a variation, use that selected
    // outgoing move before following its continuation.
    const linked = new Set(bookmark.related_moves.map((move) => move.node_id));
    let current =
      game.nodes.find(
        (node) => node.parent_id === bookmark.node_id && linked.has(node.id),
      ) ?? nodes.get(bookmark.node_id);
    while (current?.uci && result.length < 5) {
      result.push(current.uci);
      current = nodes.get(current.id);
    }
    return result;
  }
  async function save() {
    setError('');
    try {
      const lines = parseAnswerLines(fen, notation);
      setBusy(true);
      const updated = await requestJson<Definition>(url, {
        method: 'PUT',
        body: JSON.stringify({ expected_version: editVersion, prompt, lines }),
      });
      await reload(updated);
      setEditing(false);
      restart();
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 409) {
        const latest = await reload().catch(() => undefined);
        if (latest) {
          setConflict(latest);
          setEditVersion(latest.version);
        }
      }
      setError(
        failure instanceof Error ? failure.message : '保存失败，请重试。',
      );
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (confirmRemove === undefined) return;
    setBusy(true);
    setError('');
    try {
      await requestEmpty(url, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_version: confirmRemove }),
      });
      await reload({ version: 0, prompt: '', lines: [] });
      setConfirmRemove(undefined);
      setEditing(false);
      restart();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '未能删除练习');
      setConfirmRemove(undefined);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <p className="nb-practice-origin">
        {bookmark.white} — {bookmark.black} · {positionLabel(bookmark)} ·{' '}
        <Link to={`/games/${bookmark.game_id}?node=${bookmark.node_id}`}>
          回到原谱
        </Link>
      </p>
      <div className="nb-practice-grid">
        <div className="nb-practice-board">
          <WorkbenchBoard
            id="personal-practice"
            position={board.fen()}
            boardOrientation={startSide}
            animationDuration={FAST_MOVE_ANIMATION_MS}
            arePiecesDraggable={enabled}
            onSquareClick={clickSquare}
            onPieceDrop={(source, target) => submitMove(source, target)}
            customSquareStyles={lichessSquareStyles(
              board.fen(),
              selected,
              moves.at(-1),
            )}
          />
        </div>
        <section
          className="nb-practice-panel"
          aria-label={editing ? '编辑练习' : '练习内容'}
        >
          {error && <Alert type="error" showIcon title={error} />}
          {editing ? (
            <>
              <h2>编辑练习</h2>
              {conflict && (
                <div role="status">
                  <strong>另一设备保存的版本</strong>
                  <p>{conflict.prompt || '（无题目）'}</p>
                  {conflict.lines.map((line) => (
                    <p key={line.join(' ')}>{lineNotation(fen, line)}</p>
                  ))}
                  <p>下方保留了你的草稿。对照后可再次保存，或取消编辑。</p>
                </div>
              )}
              <label>
                题目
                <Input.TextArea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  maxLength={4000}
                  autoSize={{ minRows: 2, maxRows: 5 }}
                  placeholder="例如：白方怎样让王进入中心？"
                />
              </label>
              <label>
                答案变化
                <Input.TextArea
                  value={notation}
                  onChange={(e) => setNotation(e.target.value)}
                  autoSize={{ minRows: 3, maxRows: 12 }}
                  placeholder="每行一条可接受的变化，填写 SAN 着法或在棋盘上录入。"
                />
              </label>
              <div className="nb-practice-actions">
                {!recording && (
                  <Button
                    onClick={() => {
                      setRecorded([]);
                      setSelected(undefined);
                      setRecording(true);
                    }}
                  >
                    在棋盘上录入
                  </Button>
                )}
                {!recording && sourceLine().length > 0 && (
                  <Button
                    title="从原谱填入最多 5 个半回合，可继续编辑"
                    onClick={() => appendLine(lineNotation(fen, sourceLine()))}
                  >
                    填入原谱续着
                  </Button>
                )}
                {recording && (
                  <>
                    <Button
                      disabled={!recorded.length}
                      onClick={() => {
                        setRecorded(recorded.slice(0, -1));
                        setSelected(undefined);
                      }}
                    >
                      撤回一步
                    </Button>
                    <Button
                      disabled={!recorded.length}
                      onClick={() => {
                        appendLine(lineNotation(fen, recorded));
                        setRecording(false);
                        setSelected(undefined);
                      }}
                    >
                      加入答案
                    </Button>
                    <Button
                      onClick={() => {
                        setRecording(false);
                        setSelected(undefined);
                      }}
                    >
                      放弃本条录入
                    </Button>
                  </>
                )}
              </div>
              {recording && (
                <p role="status">
                  {recorded.length
                    ? lineNotation(fen, recorded)
                    : '请在棋盘上依次走出双方的着法。'}
                </p>
              )}
              <div className="nb-practice-actions">
                <Button
                  type="primary"
                  loading={busy}
                  disabled={recording}
                  onClick={() => void save()}
                >
                  保存练习
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => {
                    setEditing(false);
                    setRecording(false);
                    restart();
                  }}
                >
                  取消编辑
                </Button>
              </div>
            </>
          ) : (
            <>
              <h2>
                {definition.prompt ||
                  (definition.version
                    ? '请在棋盘上走出你的答案'
                    : '从这个局面开始练习')}
              </h2>
              {definition.version > 0 ? (
                <>
                  <p>
                    {startSide === 'white' ? '你执白' : '你执黑'}
                    。点选或拖动棋子作答，对方按保存的变化应对。
                  </p>
                  {moves.length > 0 && <p>{lineNotation(fen, moves)}</p>}
                  <p role="status">{feedback}</p>
                  {revealed && (
                    <ul>
                      {definition.lines.map((line) => (
                        <li key={line.join(' ')}>{lineNotation(fen, line)}</li>
                      ))}
                    </ul>
                  )}
                  <div className="nb-practice-actions">
                    <Button onClick={restart}>重新练习</Button>
                    <Button
                      onClick={() => {
                        setRevealed(true);
                        setSelected(undefined);
                      }}
                    >
                      查看答案
                    </Button>
                    <Button onClick={edit}>编辑练习</Button>
                    <Button
                      danger
                      onClick={() => setConfirmRemove(definition.version)}
                    >
                      删除练习
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <p>
                    写下想重做的问题和可接受的变化。下次打开时，先走棋，再看答案。
                  </p>
                  <Button type="primary" onClick={edit}>
                    创建练习
                  </Button>
                </>
              )}
              <div>
                <Link
                  to={'/analysis?' + new URLSearchParams({ fen, mode: 'play' })}
                >
                  从此局面与引擎对弈
                </Link>
              </div>
            </>
          )}
        </section>
      </div>
      {promotion && (
        <NotebookDialog
          title="选择升变棋子"
          onClose={() => setPromotion(undefined)}
        >
          <div className="nb-practice-actions">
            {Object.entries({ q: '后', r: '车', b: '象', n: '马' }).map(
              ([piece, label]) => (
                <Button
                  key={piece}
                  onClick={() =>
                    submitMove(promotion.from, promotion.to, piece)
                  }
                >
                  {label}
                </Button>
              ),
            )}
          </div>
        </NotebookDialog>
      )}
      {confirmRemove !== undefined && (
        <NotebookDialog
          title="删除这道练习？"
          busy={busy}
          onClose={() => setConfirmRemove(undefined)}
        >
          <p>题目和答案将被删除。局面收藏和个人评语会保留。</p>
          <div className="nb-practice-actions">
            <Button onClick={() => setConfirmRemove(undefined)} disabled={busy}>
              取消
            </Button>
            <Button
              danger
              type="primary"
              loading={busy}
              onClick={() => void remove()}
            >
              确认删除练习
            </Button>
          </div>
        </NotebookDialog>
      )}
    </>
  );
}
