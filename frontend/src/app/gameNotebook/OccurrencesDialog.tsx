import { useState } from 'react';
import { Link } from 'react-router-dom';
import useSWR from 'swr';
import { fetchJson } from '../../logic/api/client';
import { NotebookDialog } from './NotebookDialog';
import {
  notebookApi,
  type SavedBookmark,
  type RelatedPositions,
} from './catalogApi';
import { positionLabel } from './positionLabel';

export function OccurrencesDialog({
  bookmark,
  onClose,
  back,
}: {
  bookmark: SavedBookmark;
  onClose: () => void;
  back: { state: { notebookBack: string }; remember: () => void };
}) {
  const [variations, setVariations] = useState(false);
  const [page, setPage] = useState(0);
  const limit = 25;
  const { data, error, isLoading, mutate } = useSWR<RelatedPositions>(
    `${notebookApi}/bookmarks/${bookmark.id}/occurrences?include_variations=${variations}&offset=${page * limit}&limit=${limit}`,
    fetchJson,
  );
  return (
    <NotebookDialog title="查其他出现" onClose={onClose} wide>
      <p>
        {bookmark.white} — {bookmark.black} · {positionLabel(bookmark)}
      </p>
      <label className="nb-check">
        <input
          type="checkbox"
          checked={variations}
          onChange={(e) => {
            setVariations(e.target.checked);
            setPage(0);
          }}
        />
        包含分析变例
      </label>
      {error ? (
        <p role="alert" className="nb-error">
          查找失败。{' '}
          <button className="nb-btn" onClick={() => void mutate()}>
            重试
          </button>
        </p>
      ) : isLoading ? (
        <p role="status">正在查询棋谱…</p>
      ) : !data?.items.length ? (
        <p className="nb-empty">这个局面还没有在其他步点出现。</p>
      ) : (
        <>
          <p className="nb-muted">共 {data.total} 处</p>
          <ul className="nb-related">
            {data.items.map((node) => (
              <li key={node.node_id}>
                <Link
                  to={`/games/${node.game_id}?node=${node.node_id}`}
                  state={back.state}
                  onClick={back.remember}
                >
                  <strong>
                    {node.white} — {node.black}
                  </strong>
                  <small>
                    {[
                      node.date,
                      positionLabel(node),
                      node.archived ? '已归档' : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </small>
                </Link>
              </li>
            ))}
          </ul>
          {data.total > limit && (
            <div className="nb-actions">
              <button
                className="nb-btn"
                disabled={!page}
                onClick={() => setPage(page - 1)}
              >
                上一页
              </button>
              <span>
                {page + 1} / {Math.ceil(data.total / limit)}
              </span>
              <button
                className="nb-btn"
                disabled={(page + 1) * limit >= data.total}
                onClick={() => setPage(page + 1)}
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}
    </NotebookDialog>
  );
}
