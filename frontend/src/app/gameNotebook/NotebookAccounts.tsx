import { useEffect, useRef, useState, type FormEvent } from 'react';
import useSWR from 'swr';
import { fetchJson, requestEmpty, requestJson } from '../../logic/api/client';
import type { paths } from '../../types/api.generated';
import { NotebookDialog } from './NotebookDialog';
import './notebookAccounts.css';

const api = '/api/notebook/accounts';
type Account =
  paths[typeof api]['get']['responses'][200]['content']['application/json'][number];
type Sync =
  paths['/api/notebook/accounts/{account_id}/sync']['post']['responses'][200]['content']['application/json'];

function recentDate() {
  const now = new Date();
  now.setDate(now.getDate() - 30);
  return now.toISOString().slice(0, 10);
}

function AccountManager({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: () => void;
}) {
  const { data, error, mutate } = useSWR<Account[]>(api, fetchJson);
  const [platform, setPlatform] = useState<Account['platform']>('lichess');
  const [username, setUsername] = useState('');
  const [start, setStart] = useState(recentDate);
  const [active, setActive] = useState('');
  const [confirmDelete, setConfirmDelete] = useState('');
  const [notice, setNotice] = useState('');
  const [warning, setWarning] = useState('');
  const [adding, setAdding] = useState(false);
  const stop = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      stop.current = true;
    };
  }, []);

  function close() {
    stop.current = true;
    onImported();
    onClose();
  }

  async function synchronize(account: Account, retry = false) {
    setActive(account.id);
    setWarning('');
    setNotice('正在读取公开对局…');
    stop.current = false;
    try {
      if (retry)
        await requestJson<Account>(`${api}/${account.id}/retry`, {
          method: 'POST',
        });
      let more = true;
      while (more && !stop.current) {
        const page = await requestJson<Sync>(`${api}/${account.id}/sync`, {
          method: 'POST',
        });
        if (!alive.current) return;
        await mutate(
          (values) =>
            values?.map((item) =>
              item.id === account.id ? page.account : item,
            ),
          { revalidate: false },
        );
        more = page.more;
        setNotice(
          more
            ? `正在同步 ${account.username}，本账号累计新增 ${page.account.imported} 盘。`
            : `同步完成。${page.account.failed ? '部分棋谱未收录，可查看原因并重试。' : ''}`,
        );
      }
      if (alive.current && more)
        setNotice('同步已暂停。再次同步会从已保存的进度继续。');
    } catch (cause) {
      if (alive.current) {
        setNotice('');
        setWarning(
          cause instanceof Error ? cause.message : '同步失败，请重试。',
        );
      }
    } finally {
      onImported();
      if (alive.current) {
        setActive('');
        void mutate();
      }
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setWarning('');
    setNotice('');
    setActive('add');
    try {
      await requestJson<Account>(api, {
        method: 'POST',
        body: JSON.stringify({
          platform,
          username: username.trim(),
          start_date: start,
        }),
      });
      setUsername('');
      setAdding(false);
      setNotice('已添加账号。点「同步对局」开始收录。');
      await mutate();
    } catch (cause) {
      setWarning(cause instanceof Error ? cause.message : '添加失败。');
    } finally {
      setActive('');
    }
  }

  async function remove(account: Account) {
    setActive('remove');
    setWarning('');
    setNotice('');
    try {
      await requestEmpty(`${api}/${account.id}`, { method: 'DELETE' });
      await mutate();
      setConfirmDelete('');
      setNotice('账号已移除，已保存的棋谱仍可复盘。');
    } catch (cause) {
      setWarning(cause instanceof Error ? cause.message : '移除失败。');
    } finally {
      setActive('');
    }
  }

  return (
    <NotebookDialog
      title="对局账号"
      onClose={close}
      busy={active === 'add' || active === 'remove'}
    >
      {error && (
        <p role="alert" className="nb-error">
          读取账号列表失败。{' '}
          <button className="nb-btn" onClick={() => void mutate()}>
            重试
          </button>
        </p>
      )}
      {!error && !data && <p role="status">正在读取账号…</p>}
      {data && !data.length && (
        <p>添加公开账号后，可以按日期把已结束的标准棋局同步到我的棋谱。</p>
      )}
      {data?.map((account) => (
        <section key={account.id} className="nb-account-row">
          <h3>
            {account.username}{' '}
            <small>
              {account.platform === 'lichess' ? 'Lichess' : 'Chess.com'}
            </small>
          </h3>
          <p>
            从 {account.start_date} 收录 ·{' '}
            {account.last_synced_ms
              ? `最近同步于 ${new Date(account.last_synced_ms).toLocaleString()}`
              : '尚未完成同步'}
          </p>
          <p>
            已新增 {account.imported} 盘，已有 {account.existing} 盘
            {account.queued > 0 && `，待收录 ${account.queued} 盘`}
            {account.waiting > 0 && `，等待终局 ${account.waiting} 盘`}
          </p>
          {account.failed > 0 && (
            <p className="nb-error">
              有 {account.failed} 盘未能收录。{account.last_error}
            </p>
          )}
          <div className="nb-account-actions">
            {active === account.id ? (
              <button
                className="nb-btn"
                onClick={() => {
                  stop.current = true;
                  setNotice('完成当前小批次后暂停…');
                }}
              >
                暂停同步
              </button>
            ) : (
              <button
                className="nb-btn primary"
                disabled={!!active}
                onClick={() => void synchronize(account)}
              >
                同步对局
              </button>
            )}
            {account.failed > 0 && (
              <button
                className="nb-btn"
                disabled={!!active}
                onClick={() => void synchronize(account, true)}
              >
                重试失败棋谱
              </button>
            )}
            <button
              className="nb-btn"
              disabled={!!active}
              onClick={() => {
                setConfirmDelete(account.id);
                setWarning('');
              }}
            >
              移除账号
            </button>
          </div>
          {confirmDelete === account.id && (
            <div className="nb-account-confirm">
              <p>
                移除 {account.username}{' '}
                的同步记录？已保存的棋谱、评语和收藏都会保留。
              </p>
              <button
                className="nb-btn danger"
                disabled={!!active}
                onClick={() => void remove(account)}
              >
                确认移除账号
              </button>{' '}
              <button
                className="nb-btn"
                disabled={!!active}
                onClick={() => setConfirmDelete('')}
              >
                取消
              </button>
            </div>
          )}
        </section>
      ))}
      {adding || data?.length === 0 ? (
        <form onSubmit={add} className="nb-account-form">
          <label className="nb-field">
            平台
            <select
              value={platform}
              onChange={(e) =>
                setPlatform(e.target.value as Account['platform'])
              }
            >
              <option value="lichess">Lichess</option>
              <option value="chess.com">Chess.com</option>
            </select>
          </label>
          <label className="nb-field">
            公开用户名
            <input
              required
              maxLength={40}
              pattern="[A-Za-z0-9_\-]+"
              autoComplete="off"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <label className="nb-field">
            同步起始日期（UTC）
            <input
              type="date"
              required
              value={start}
              min="2000-01-01"
              max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <div className="nb-account-actions">
            <button className="nb-btn primary" disabled={!!active}>
              添加账号
            </button>
            {!!data?.length && (
              <button
                type="button"
                className="nb-btn"
                onClick={() => setAdding(false)}
              >
                取消
              </button>
            )}
          </div>
        </form>
      ) : (
        data && (
          <button
            className="nb-btn"
            disabled={!!active}
            onClick={() => setAdding(true)}
          >
            添加对局账号
          </button>
        )
      )}
      {notice && (
        <p role="status" className="nb-notice">
          {notice}
        </p>
      )}
      {warning && (
        <p role="alert" className="nb-error">
          {warning}
        </p>
      )}
    </NotebookDialog>
  );
}

export function NotebookAccounts({ onImported }: { onImported: () => void }) {
  const [opened, setOpened] = useState(false);
  return (
    <>
      <button className="nb-btn" onClick={() => setOpened(true)}>
        对局账号
      </button>
      {opened && (
        <AccountManager
          onClose={() => setOpened(false)}
          onImported={onImported}
        />
      )}
    </>
  );
}
