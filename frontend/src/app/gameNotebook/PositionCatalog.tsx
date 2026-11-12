import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import useSWR, { useSWRConfig } from 'swr';
import {
  ApiError,
  fetchJson,
  requestEmpty,
  requestJson,
} from '../../logic/api/client';
import { BookmarkEditor, type BookmarkFields } from './BookmarkEditor';
import { CatalogShell } from './CatalogShell';
import { NoteExcerpt } from './NoteExcerpt';
import { NotebookDialog } from './NotebookDialog';
import { OccurrencesDialog } from './OccurrencesDialog';
import { PositionThumbnail } from './PositionThumbnail';
import {
  notebookApi,
  type SavedBookmark,
  type BookmarkResults,
} from './catalogApi';
import { useCatalogReturn } from './catalogNavigation';
import { positionLabel } from './positionLabel';

const pageSize = 24;
const matchNames = {
  title: '标题',
  tag: '标签',
  note: '局面评语',
  move_note: '棋步评语',
};

export function PositionCatalog() {
  const [params, setParams] = useSearchParams();
  const query = params.get('q') ?? '';
  const tags = params.getAll('tag');
  const page = Math.max(1, parseInt(params.get('page') || '1', 10) || 1);
  const key = useMemo(() => {
    const values = new URLSearchParams();
    if (query.trim()) values.set('q', query.trim());
    params.getAll('tag').forEach((tag) => values.append('tag', tag));
    values.set('offset', String((page - 1) * pageSize));
    values.set('limit', String(pageSize));
    return `${notebookApi}/bookmarks?${values}`;
  }, [params, page, query]);
  const { data, isLoading, isValidating, error, mutate } =
    useSWR<BookmarkResults>(key, fetchJson, {
      keepPreviousData: true,
      revalidateOnFocus: true,
    });
  const { data: tagData, mutate: refreshTags } = useSWR<{ tags: string[] }>(
    notebookApi + '/bookmark-tags',
    fetchJson,
    { revalidateOnFocus: true },
  );
  const { mutate: mutateAll } = useSWRConfig();
  const back = useCatalogReturn(data !== undefined && !isLoading);
  const [editing, setEditing] = useState<SavedBookmark>();
  const [related, setRelated] = useState<SavedBookmark>();
  const [deleting, setDeleting] = useState<SavedBookmark>();
  const [removed, setRemoved] = useState<SavedBookmark>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    if (
      data &&
      !isValidating &&
      page > 1 &&
      page > Math.max(1, Math.ceil(data.total / pageSize))
    ) {
      const next = new URLSearchParams(params);
      const last = Math.max(1, Math.ceil(data.total / pageSize));
      if (last === 1) next.delete('page');
      else next.set('page', String(last));
      setParams(next, { replace: true });
    }
  }, [page, params, data, isValidating, setParams]);

  function filter(key: 'q' | 'tag', value: string) {
    const next = new URLSearchParams(params);
    next.delete('page');
    if (key === 'tag') {
      const selected = next.getAll('tag');
      next.delete('tag');
      (selected.includes(value)
        ? selected.filter((tag) => tag !== value)
        : [...selected, value]
      ).forEach((tag) => next.append('tag', tag));
    } else if (value) next.set('q', value);
    else next.delete('q');
    setParams(next, { replace: true });
  }
  function goPage(value: number) {
    const next = new URLSearchParams(params);
    if (value > 1) next.set('page', String(value));
    else next.delete('page');
    setParams(next);
    window.scrollTo(0, 0);
  }
  async function refresh() {
    await Promise.all([
      mutate(),
      refreshTags(),
      mutateAll(
        (k) => typeof k === 'string' && k.startsWith(notebookApi + '/games/'),
      ),
    ]);
  }
  async function saveBookmark(bookmark: SavedBookmark, fields: BookmarkFields) {
    const url = `${notebookApi}/bookmarks/${bookmark.id}`;
    try {
      await requestJson<SavedBookmark>(url, {
        method: 'PATCH',
        body: JSON.stringify({ expected_version: bookmark.version, ...fields }),
      });
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        const latest = await fetchJson<SavedBookmark>(url);
        setEditing(latest);
        throw new Error(
          '此收藏已在其他设备修改。请比较最新内容，然后重新保存。',
        );
      }
      throw cause;
    }
    setNotice('收藏已保存');
    setRemoved(undefined);
    await refresh();
  }
  async function mark(bookmark: SavedBookmark, active: boolean) {
    if (busy) return;
    setBusy(true);
    setActionError('');
    setNotice('');
    try {
      const updated = await requestJson<SavedBookmark>(
        `${notebookApi}/bookmarks/${bookmark.id}`,
        {
          method: 'PATCH',
          body: JSON.stringify({ expected_version: bookmark.version, active }),
        },
      );
      setRemoved(active ? undefined : updated);
      setNotice(
        active ? '收藏已恢复。' : '已取消收藏，重新收藏时可以恢复评语和标签。',
      );
      await refresh();
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : '保存失败，请重试',
      );
    } finally {
      setBusy(false);
    }
  }
  async function erase(bookmark: SavedBookmark) {
    if (busy) return;
    setBusy(true);
    setActionError('');
    try {
      await requestEmpty(
        `${notebookApi}/bookmarks/${bookmark.id}?expected_version=${bookmark.version}`,
        { method: 'DELETE' },
      );
      setDeleting(undefined);
      setRemoved(undefined);
      setNotice('收藏与局面笔记已删除。');
      await refresh();
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : '删除失败，请重试',
      );
    } finally {
      setBusy(false);
    }
  }
  const tagOptions = Array.from(new Set([...(tagData?.tags ?? []), ...tags]));
  return (
    <CatalogShell title="局面收藏">
      <div className="nb-filters">
        <label className="nb-field nb-search-field">
          搜索局面
          <input
            type="search"
            maxLength={500}
            value={query}
            onChange={(e) => filter('q', e.target.value)}
            placeholder="标题、标签或评语中的文字"
          />
        </label>
        {tagOptions.length > 0 && (
          <details className="nb-details nb-tag-filter">
            <summary>
              按标签筛选{tags.length ? `（${tags.length}）` : ''}
            </summary>
            <div className="nb-tags" aria-label="标签筛选">
              {tagOptions.map((tag) => (
                <button
                  type="button"
                  className={
                    'nb-chip' + (tags.includes(tag) ? ' selected' : '')
                  }
                  key={tag}
                  aria-pressed={tags.includes(tag)}
                  onClick={() => filter('tag', tag)}
                >
                  {tag}
                </button>
              ))}
            </div>
          </details>
        )}
        {(query || tags.length > 0) && (
          <button
            className="nb-btn"
            onClick={() => setParams({}, { replace: true })}
          >
            清除筛选
          </button>
        )}
      </div>
      {tags.length > 0 && (
        <div className="nb-tags nb-applied" aria-label="当前筛选">
          {tags.map((tag) => (
            <button
              key={tag}
              className="nb-chip selected"
              aria-label={`取消筛选 ${tag}`}
              onClick={() => filter('tag', tag)}
            >
              {tag} ×
            </button>
          ))}
        </div>
      )}
      {notice && (
        <div role="status" className="nb-notice nb-actions">
          {notice}
          {removed && (
            <button
              className="nb-btn"
              disabled={busy}
              onClick={() => void mark(removed, true)}
            >
              撤销
            </button>
          )}
        </div>
      )}
      {actionError && !deleting && (
        <p role="alert" className="nb-error">
          {actionError}
        </p>
      )}
      {error ? (
        <p role="alert" className="nb-error">
          加载收藏失败。{' '}
          <button className="nb-btn" onClick={() => void mutate()}>
            重试
          </button>
        </p>
      ) : !data && isLoading ? (
        <p role="status">正在读取局面…</p>
      ) : !data?.items.length ? (
        <p className="nb-empty">
          {query || tags.length
            ? '没有匹配的局面，请调整关键词或标签。'
            : '还没有局面收藏。打开一盘棋，走到想记住的位置，再点「收藏当前局面」。'}
        </p>
      ) : (
        <>
          <p className="nb-result-count" role="status">
            {isLoading ? '正在筛选…' : `共 ${data.total} 个局面`}
          </p>
          <ul className="nb-positions">
            {data.items.map((item) => {
              const text = positionLabel(item),
                source = `/games/${item.game_id}?node=${item.node_id}`;
              const relatedNotes = item.related_moves.filter((move) =>
                move.note.trim(),
              );
              const label =
                item.title ||
                `${item.white} — ${item.black} · ${text.split(' · ').slice(0, 2).join(' · ')}`;
              return (
                <li className="nb-position" key={item.id}>
                  <div className="nb-position-top">
                    <PositionThumbnail fen={item.fen} label="收藏的局面" />
                    <div>
                      <h2>
                        <Link
                          to={source}
                          state={back.state}
                          onClick={back.remember}
                        >
                          {label}
                        </Link>
                      </h2>
                      {item.title && (
                        <p className="nb-meta">
                          {item.white} — {item.black}
                        </p>
                      )}
                      <p className="nb-meta">{text}</p>
                      <p className="nb-meta">
                        {[item.date, item.archived ? '原谱已归档' : null]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                    </div>
                  </div>
                  {item.tags.length > 0 && (
                    <div className="nb-tags">
                      {item.tags.map((tag) => (
                        <button
                          key={tag}
                          className={
                            'nb-chip' + (tags.includes(tag) ? ' selected' : '')
                          }
                          aria-pressed={tags.includes(tag)}
                          onClick={() => filter('tag', tag)}
                        >
                          {tag}
                        </button>
                      ))}
                    </div>
                  )}
                  {item.matches.length ? (
                    <div className="nb-match">
                      {item.matches.map((m, index) => (
                        <p key={index}>
                          <strong>{matchNames[m.field]}</strong> {m.text}
                        </p>
                      ))}
                    </div>
                  ) : item.note ? (
                    <NoteExcerpt text={item.note} />
                  ) : null}
                  {relatedNotes.length > 0 && (
                    <details className="nb-details nb-related-notes">
                      <summary>关联棋步评语（{relatedNotes.length}）</summary>
                      {relatedNotes.map((move) => (
                        <p key={move.node_id} className="nb-summary">
                          <Link
                            to={`/games/${item.game_id}?node=${move.node_id}`}
                            state={back.state}
                            onClick={back.remember}
                          >
                            {move.san}
                          </Link>{' '}
                          {move.note}
                        </p>
                      ))}
                    </details>
                  )}
                  <div className="nb-actions nb-card-actions">
                    <Link
                      className="nb-btn"
                      to={source}
                      state={back.state}
                      onClick={back.remember}
                    >
                      回到收藏处
                    </Link>
                    <button className="nb-btn" onClick={() => setRelated(item)}>
                      查其他出现
                    </button>
                    <button
                      className="nb-btn"
                      onClick={() => {
                        setEditing(item);
                        setActionError('');
                      }}
                    >
                      编辑收藏
                    </button>
                    <Link
                      className="nb-btn"
                      to={`/games/positions/${item.id}/practice`}
                      state={back.state}
                      onClick={back.remember}
                    >
                      练习局面
                    </Link>
                    <details className="nb-details nb-manage">
                      <summary>管理收藏</summary>
                      <div className="nb-actions">
                        <button
                          className="nb-btn"
                          disabled={busy}
                          onClick={() => void mark(item, false)}
                        >
                          取消收藏
                        </button>
                        <button
                          className="nb-btn danger"
                          disabled={busy}
                          onClick={() => {
                            setActionError('');
                            setDeleting(item);
                          }}
                        >
                          删除收藏
                        </button>
                      </div>
                    </details>
                  </div>
                </li>
              );
            })}
          </ul>
          {data.total > pageSize && (
            <div className="nb-actions nb-pagination">
              <button
                className="nb-btn"
                disabled={page <= 1}
                onClick={() => goPage(page - 1)}
              >
                上一页
              </button>
              <span>
                {page} / {Math.ceil(data.total / pageSize)}
              </span>
              <button
                className="nb-btn"
                disabled={page * pageSize >= data.total}
                onClick={() => goPage(page + 1)}
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}
      {editing && (
        <BookmarkEditor
          key={editing.id}
          initial={{
            title: editing.title,
            note: editing.note,
            tags: editing.tags,
          }}
          suggestedTags={tagOptions}
          onSave={(fields) => saveBookmark(editing, fields)}
          onClose={() => setEditing(undefined)}
        />
      )}
      {related && (
        <OccurrencesDialog
          bookmark={related}
          back={back}
          onClose={() => setRelated(undefined)}
        />
      )}
      {deleting && (
        <NotebookDialog
          title="删除收藏"
          onClose={() => setDeleting(undefined)}
          busy={busy}
        >
          <p>
            永久删除这条局面收藏的标题、标签、局面评语和已编写的练习？原棋谱和棋步评语会保留。
          </p>
          {actionError && (
            <p role="alert" className="nb-error">
              {actionError}
            </p>
          )}
          <div className="nb-actions">
            <button
              className="nb-btn danger"
              disabled={busy}
              onClick={() => void erase(deleting)}
            >
              确认删除收藏
            </button>
            <button
              className="nb-btn"
              disabled={busy}
              onClick={() => setDeleting(undefined)}
            >
              取消
            </button>
          </div>
        </NotebookDialog>
      )}
    </CatalogShell>
  );
}
