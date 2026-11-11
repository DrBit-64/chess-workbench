import { Popconfirm } from 'antd';
import { useState } from 'react';
import { OccurrencesDialog } from './OccurrencesDialog';
import { Link, useLocation } from 'react-router-dom';

import { positionLabel } from './positionLabel';
import {
  moveLabel,
  type ReviewGame,
  type ReviewNode,
  type ReviewBookmark,
} from './reviewTypes';

export function ReviewPositionNotes({
  active,
  node,
  byId,
  bookmark,
  busy,
  star,
  unstar,
  editNote,
  editBookmark,
  select,
}: {
  active: boolean;
  node: ReviewNode;
  byId: ReadonlyMap<string, ReviewNode>;
  bookmark: ReviewBookmark | undefined;
  busy: boolean;
  star: () => void;
  unstar: (permanent: boolean) => Promise<void>;
  editNote: () => void;
  editBookmark: (bookmark: ReviewBookmark) => void;
  select: (node: ReviewNode) => void;
}) {
  const location = useLocation();
  const [showOccurrences, setShowOccurrences] = useState(false);
  return (
    <section
      className="game-review-sheet game-review-notes"
      data-active={active}
      aria-label="评语与收藏面板"
    >
      <h2>{moveLabel(node)}</h2>
      <p className="game-review-caption">{positionLabel(node)}</p>
      {(node.starting_comment || node.comment) && (
        <div className="game-review-note-section">
          <h3>原谱评注</h3>
          {node.starting_comment && (
            <p className="game-review-prose">{node.starting_comment}</p>
          )}
          {node.comment && <p className="game-review-prose">{node.comment}</p>}
        </div>
      )}
      {node.san && (
        <div className="game-review-note-section">
          <h3>棋步评语</h3>
          {node.note && <p className="game-review-prose">{node.note}</p>}
          <button
            type="button"
            className="game-review-action"
            onClick={editNote}
          >
            {node.note ? '编辑棋步评语' : '写棋步评语'}
          </button>
        </div>
      )}
      <div className="game-review-note-section">
        <h3>{bookmark?.title || '局面收藏'}</h3>
        {bookmark ? (
          <>
            {bookmark.tags.length > 0 && (
              <ul className="game-review-tags">
                {bookmark.tags.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            )}
            {bookmark.note && (
              <p className="game-review-prose">{bookmark.note}</p>
            )}
            {bookmark.related_moves.length > 0 && (
              <div className="game-review-related">
                <h4>关联棋步</h4>
                {bookmark.related_moves.map((item) => {
                  const attachment = byId.get(item.node_id);
                  return (
                    attachment && (
                      <p key={item.node_id}>
                        <button
                          type="button"
                          onClick={() => select(attachment)}
                        >
                          {moveLabel(attachment)}
                        </button>
                        {item.note && attachment.id !== node.id && (
                          <span className="game-review-linked-note">
                            {item.note}
                          </span>
                        )}
                      </p>
                    )
                  );
                })}
              </div>
            )}
            <div className="game-review-actions">
              <button
                type="button"
                className="game-review-action"
                onClick={() => editBookmark(bookmark)}
              >
                编辑收藏笔记
              </button>
              <button
                type="button"
                className="game-review-action"
                onClick={() => setShowOccurrences(true)}
              >
                查其他出现
              </button>
              <Link
                className="game-review-action"
                to={`/games/positions/${bookmark.id}/practice`}
                state={{ notebookBack: location.pathname + location.search }}
              >
                练习此局面
              </Link>
              <button
                type="button"
                className="game-review-action"
                disabled={busy}
                onClick={() => void unstar(false)}
              >
                取消收藏
              </button>
              <Popconfirm
                title="永久删除这个收藏？"
                description="这会永久删除此处收藏的标题、标签、笔记和练习题。原谱和棋步评语仍可查看。"
                styles={{ root: { maxWidth: 'calc(100vw - 16px)' } }}
                okText="永久删除"
                cancelText="取消"
                onConfirm={() => unstar(true)}
              >
                <button
                  type="button"
                  className="game-review-action danger"
                  disabled={busy}
                >
                  删除收藏
                </button>
              </Popconfirm>
            </div>
          </>
        ) : (
          <button
            type="button"
            className="game-review-action"
            disabled={busy}
            onClick={star}
          >
            收藏此局面
          </button>
        )}
      </div>
      {showOccurrences && bookmark && (
        <OccurrencesDialog
          bookmark={bookmark}
          onClose={() => setShowOccurrences(false)}
          back={{
            state: { notebookBack: location.pathname + location.search },
            remember: () => setShowOccurrences(false),
          }}
        />
      )}
    </section>
  );
}

export function ReviewGameInfo({
  active,
  game,
  url,
  editSummary,
}: {
  active: boolean;
  game: ReviewGame;
  url: string;
  editSummary: () => void;
}) {
  const sourceLink = /^https?:\/\//i.test(game.source_url ?? '')
    ? game.source_url
    : null;
  return (
    <section
      className="game-review-sheet game-review-info"
      data-active={active}
      aria-label="对局信息面板"
    >
      <h2>对局信息</h2>
      <div className="game-review-info-links">
        <a href={`${url}/pgn`} download>
          下载原始 PGN
        </a>
        {sourceLink && (
          <a href={sourceLink} target="_blank" rel="noreferrer">
            打开原站对局 ↗
          </a>
        )}
      </div>
      <div className="game-review-note-section">
        <h3>整盘总结</h3>
        {game.summary && <p className="game-review-prose">{game.summary}</p>}
        <button
          type="button"
          className="game-review-action"
          onClick={editSummary}
        >
          {game.summary ? '编辑整盘总结' : '写整盘总结'}
        </button>
      </div>
      <details className="game-review-headers">
        <summary>棋谱信息</summary>
        <dl>
          {Object.entries(game.headers).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}
