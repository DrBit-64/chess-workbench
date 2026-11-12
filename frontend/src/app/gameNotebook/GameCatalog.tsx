import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import useSWR from 'swr';
import {
  ApiError,
  fetchJson,
  requestEmpty,
  requestJson,
} from '../../logic/api/client';
import { CatalogShell } from './CatalogShell';
import { GameImportDialog } from './GameImportDialog';
import { gameTimeControl } from './gameTimeControl';
import { NotebookAccounts } from './NotebookAccounts';
import { GameCard } from './GameCard';
import { NotebookDialog } from './NotebookDialog';
import { notebookApi, type GameResults, type SavedGame } from './catalogApi';
import { useCatalogReturn } from './catalogNavigation';

const pageSize = 30;

export function GameCatalog() {
  const [params, setParams] = useSearchParams();
  const archived = params.get('archived') === '1';
  const query = params.get('q') ?? '';
  const order = params.get('order') === 'asc' ? 'asc' : 'desc';
  const timeControl = params.get('time_control') ?? '';
  const navigate = useNavigate();
  const page = Math.max(1, parseInt(params.get('page') || '1', 10) || 1);
  const values = new URLSearchParams({
    archived: String(archived),
    order,
    limit: String(pageSize),
    offset: String((page - 1) * pageSize),
  });
  if (query.trim()) values.set('q', query.trim());
  if (timeControl) values.set('time_control', timeControl);
  const key = `${notebookApi}/game-catalog?${values}`;
  const { data, error, isLoading, mutate } = useSWR<GameResults>(
    key,
    fetchJson,
    { revalidateOnFocus: true },
  );
  const [importing, setImporting] = useState(false);
  const [deleting, setDeleting] = useState<SavedGame>();
  const [busy, setBusy] = useState<string>();
  const [notice, setNotice] = useState('');
  const [actionError, setActionError] = useState('');
  const back = useCatalogReturn(data !== undefined);
  const games = data?.items ?? [];
  // Keep the selected control visible while loading or when a search yields no games.
  const clockOptions = new Set(
    (data?.time_controls ?? []).map((value) => value ?? '?'),
  );
  if (timeControl) clockOptions.add(timeControl);
  useEffect(() => {
    if (!data || page <= 1 || (page - 1) * pageSize < data.total) return;
    const next = new URLSearchParams(params);
    const last = Math.max(1, Math.ceil(data.total / pageSize));
    if (last === 1) next.delete('page');
    else next.set('page', String(last));
    setParams(next, { replace: true });
  }, [data, page, params, setParams]);
  function updateParams(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (key !== 'page') next.delete('page');
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }
  async function changeGame(
    game: SavedGame,
    action: 'archive' | 'restore' | 'delete',
  ) {
    if (busy) return;
    setBusy(game.id);
    setNotice('');
    setActionError('');
    try {
      if (action === 'delete')
        await requestEmpty(
          `${notebookApi}/games/${game.id}?expected_version=${game.version}`,
          { method: 'DELETE' },
        );
      else
        await requestJson(`${notebookApi}/games/${game.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            expected_version: game.version,
            archived: action === 'archive',
          }),
        });
      setDeleting(undefined);
      setNotice(
        action === 'delete'
          ? '棋谱已永久删除'
          : action === 'archive'
            ? '棋谱已归档，可在「已归档」中恢复或删除。'
            : '棋谱已恢复',
      );
      await mutate(
        (current) =>
          current && {
            ...current,
            total: Math.max(0, current.total - 1),
            items: current.items.filter((item) => item.id !== game.id),
          },
        { revalidate: true },
      );
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : '操作失败，请重试。',
      );
      const fresh = await mutate();
      if (
        action === 'delete' &&
        cause instanceof ApiError &&
        cause.status === 409
      ) {
        setDeleting(fresh?.items.find((item) => item.id === game.id));
      }
    } finally {
      setBusy(undefined);
    }
  }

  return (
    <CatalogShell
      title="我的棋谱"
      actions={
        <>
          <NotebookAccounts
            onImported={() => {
              void mutate();
            }}
          />
          <button className="nb-btn primary" onClick={() => setImporting(true)}>
            收录棋谱
          </button>
        </>
      }
    >
      <div className="nb-filters nb-game-filters">
        <div className="nb-segment">
          <button
            aria-pressed={!archived}
            onClick={() => {
              setActionError('');
              updateParams('archived', '');
            }}
          >
            已收录
          </button>
          <button
            aria-pressed={archived}
            onClick={() => {
              setActionError('');
              updateParams('archived', '1');
            }}
          >
            已归档
          </button>
        </div>
        <label className="nb-field nb-search-field">
          搜索棋谱
          <input
            type="search"
            maxLength={500}
            value={query}
            placeholder="棋手、日期或整盘总结"
            onChange={(e) => updateParams('q', e.target.value)}
          />
        </label>
        <div className="nb-game-selects">
          <label className="nb-field">
            对局时间排序
            <select
              value={order}
              onChange={(e) =>
                updateParams('order', e.target.value === 'asc' ? 'asc' : '')
              }
            >
              <option value="desc">最新在前</option>
              <option value="asc">最早在前</option>
            </select>
          </label>
          <label className="nb-field">
            对局时限
            <select
              value={timeControl}
              onChange={(e) => updateParams('time_control', e.target.value)}
            >
              <option value="">全部时限</option>
              {[...clockOptions].map((value) => (
                <option key={value} value={value}>
                  {gameTimeControl(value)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      {notice && (
        <p role="status" className="nb-notice">
          {notice}
        </p>
      )}
      {actionError && !deleting && (
        <p role="alert" className="nb-error">
          {actionError}
        </p>
      )}
      {error ? (
        <p role="alert" className="nb-error">
          棋谱列表读取失败。{' '}
          <button className="nb-btn" onClick={() => void mutate()}>
            重试
          </button>
        </p>
      ) : isLoading ? (
        <p role="status">正在读取棋谱…</p>
      ) : games.length === 0 ? (
        <p className="nb-empty">
          {query || timeControl
            ? '没有符合条件的棋谱。'
            : archived
              ? '没有归档的棋谱。'
              : '还没有收藏棋谱。可以从 PGN 或对局链接开始。'}
        </p>
      ) : (
        <ul className="nb-game-grid">
          {games.map((game) => (
            <GameCard
              key={game.id}
              game={game}
              returnState={back.state}
              onOpen={back.remember}
            >
              {archived ? (
                <>
                  <button
                    className="nb-btn"
                    disabled={!!busy}
                    onClick={() => void changeGame(game, 'restore')}
                  >
                    恢复
                  </button>
                  <button
                    className="nb-btn danger"
                    disabled={!!busy}
                    onClick={() => {
                      setActionError('');
                      setDeleting(game);
                    }}
                  >
                    永久删除
                  </button>
                </>
              ) : (
                <button
                  className="nb-btn"
                  disabled={!!busy}
                  onClick={() => void changeGame(game, 'archive')}
                >
                  归档
                </button>
              )}
            </GameCard>
          ))}
        </ul>
      )}
      {data && data.total > pageSize && (
        <div className="nb-actions nb-pagination">
          <button
            className="nb-btn"
            disabled={page <= 1}
            onClick={() => {
              updateParams('page', page === 2 ? '' : String(page - 1));
              window.scrollTo(0, 0);
            }}
          >
            上一页
          </button>
          <span>
            {page} / {Math.ceil(data.total / pageSize)} · 共 {data.total} 盘
          </span>
          <button
            className="nb-btn"
            disabled={page * pageSize >= data.total}
            onClick={() => {
              updateParams('page', String(page + 1));
              window.scrollTo(0, 0);
            }}
          >
            下一页
          </button>
        </div>
      )}
      {importing && (
        <GameImportDialog
          onClose={() => setImporting(false)}
          onImported={(result) => {
            setImporting(false);
            void mutate();
            if (result.games.length === 1) {
              back.remember();
              void navigate('/games/' + result.games[0].id, {
                state: back.state,
              });
            } else {
              setParams(new URLSearchParams(), { replace: true });
              setNotice(
                `已处理 ${result.games.length} 盘，其中新收录 ${result.games.filter((game) => game.created).length} 盘。`,
              );
            }
          }}
        />
      )}
      {deleting && (
        <NotebookDialog
          title="永久删除棋谱"
          onClose={() => setDeleting(undefined)}
          busy={!!busy}
        >
          <p>
            将删除「{deleting.white} — {deleting.black}
            」的本地棋谱、个人评语、局面收藏及其练习。此操作无法撤销。
          </p>
          {actionError && (
            <p className="nb-error" role="alert">
              {actionError}
            </p>
          )}
          <div className="nb-actions">
            <button
              className="nb-btn danger"
              disabled={!!busy}
              onClick={() => void changeGame(deleting, 'delete')}
            >
              确认永久删除
            </button>
            <button
              className="nb-btn"
              disabled={!!busy}
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
