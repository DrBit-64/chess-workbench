import { useId, useRef, useState, type FormEvent } from 'react';
import { requestJson } from '../../logic/api/client';
import { NotebookDialog } from './NotebookDialog';
import {
  notebookApi,
  type ImportPreview,
  type ImportResult,
} from './catalogApi';

type Selection = {
  index: number;
  action: 'save' | 'copy' | 'open';
  existing_id?: string;
};

export function GameImportDialog({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (result: ImportResult) => void;
}) {
  const [tab, setTab] = useState<'pgn' | 'url'>('pgn');
  const [pgn, setPgn] = useState('');
  const [url, setUrl] = useState('');
  const [username, setUsername] = useState('');
  const [month, setMonth] = useState('');
  const [preview, setPreview] = useState<ImportPreview>();
  const [selected, setSelected] = useState<number[]>([]);
  const [choices, setChoices] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [readingFile, setReadingFile] = useState(false);
  const [error, setError] = useState('');
  const formId = useId();
  const fileRead = useRef(0);
  const submission = useRef<{ key: string; id: string }>();
  const link = /^(?:www\.)?(?:lichess\.org|chess\.com)\//i.test(url.trim())
    ? 'https://' + url.trim()
    : url.trim();
  const isChessCom = /^https?:\/\/(?:www\.)?chess\.com\//i.test(link);

  async function load(file?: File) {
    if (!file) return;
    const revision = ++fileRead.current;
    setReadingFile(true);
    setError('');
    try {
      const bytes = await file.arrayBuffer();
      const text = new TextDecoder('utf-8', {
        fatal: true,
        ignoreBOM: true,
      }).decode(bytes);
      if (revision === fileRead.current) setPgn(text);
    } catch {
      if (revision === fileRead.current)
        setError(
          '无法读取此 PGN 文件。请另存为 UTF-8 编码后重选，或直接粘贴棋谱。',
        );
    } finally {
      if (revision === fileRead.current) setReadingFile(false);
    }
  }

  async function inspect(event: FormEvent) {
    event.preventDefault();
    if (busy || readingFile) return;
    setBusy(true);
    setError('');
    const source =
      tab === 'pgn'
        ? { pgn }
        : {
            url: link,
            ...(isChessCom && username.trim()
              ? { username: username.trim() }
              : {}),
            ...(isChessCom && month ? { month } : {}),
          };
    try {
      const next = await requestJson<ImportPreview>(
        notebookApi + '/imports/preview',
        { method: 'POST', body: JSON.stringify(source) },
      );
      if (!next.games.length) throw Error('没有可收录的棋局，请检查 PGN。');
      setPreview(next);
      setSelected(next.games.map((game) => game.index));
      setChoices({});
      submission.current = undefined;
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : '获取棋谱失败，请重试或改用 PGN。',
      );
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!preview || busy) return;
    const selections: Selection[] = [];
    for (const game of preview.games) {
      if (!selected.includes(game.index)) continue;
      const choice = choices[game.index];
      if (!game.existing_id && game.possible_duplicates.length) {
        if (!choice) {
          setError('请为所选的疑似重复棋谱选择打开原谱或另存一盘。');
          return;
        }
        selections.push(
          choice === 'copy'
            ? { index: game.index, action: 'copy' }
            : { index: game.index, action: 'open', existing_id: choice },
        );
      } else selections.push({ index: game.index, action: 'save' });
    }
    if (!selections.length) return;
    const key = JSON.stringify(selections);
    if (submission.current?.key !== key) {
      // getRandomValues is available on plain LAN HTTP as well as HTTPS.
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 15) | 64;
      bytes[8] = (bytes[8] & 63) | 128;
      const hex = Array.from(bytes, (b) =>
        b.toString(16).padStart(2, '0'),
      ).join('');
      submission.current = {
        key,
        id: [
          hex.slice(0, 8),
          hex.slice(8, 12),
          hex.slice(12, 16),
          hex.slice(16, 20),
          hex.slice(20),
        ].join('-'),
      };
    }
    setBusy(true);
    setError('');
    try {
      const result = await requestJson<ImportResult>(notebookApi + '/imports', {
        method: 'POST',
        body: JSON.stringify({
          pgn: preview.pgn,
          source_url: preview.source_url,
          selections,
          request_id: submission.current.id,
        }),
      });
      onImported(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '收录失败，请重试。');
    } finally {
      setBusy(false);
    }
  }
  const gameLabel = (id: string) => {
    const game = preview?.duplicate_games.find((item) => item.id === id);
    if (!game) return `已有棋谱 · ${id.slice(0, 8)}`;
    const added = new Date(game.created_at).toLocaleString();
    return [
      game.white + ' — ' + game.black,
      '收录于 ' + added,
      game.archived_at ? '已归档' : '',
      game.summary.slice(0, 36),
    ]
      .filter(Boolean)
      .join(' · ');
  };

  return (
    <NotebookDialog
      title={preview ? '选择要收录的棋谱' : '收录棋谱'}
      onClose={onClose}
      busy={busy}
      wide
      footer={
        preview ? (
          <>
            <button
              type="submit"
              form={formId}
              className="nb-btn primary"
              disabled={busy || !selected.length}
            >
              {busy ? `正在收录 ${selected.length} 盘…` : '收录所选棋谱'}
            </button>
            <button
              type="button"
              className="nb-btn"
              disabled={busy}
              onClick={() => {
                setPreview(undefined);
                setError('');
              }}
            >
              返回修改
            </button>
          </>
        ) : (
          <button
            type="submit"
            form={formId}
            className="nb-btn primary"
            disabled={
              busy || readingFile || !(tab === 'pgn' ? pgn.trim() : url.trim())
            }
          >
            {busy ? '正在读取…' : '预览棋谱'}
          </button>
        )
      }
    >
      {preview ? (
        <form
          id={formId}
          className="nb-form"
          onSubmit={(event) => void submit(event)}
        >
          <div className="nb-actions">
            <span>
              已选 {selected.length} / {preview.games.length} 盘
            </span>
            <button
              type="button"
              className="nb-btn"
              disabled={busy}
              onClick={() =>
                setSelected(
                  selected.length === preview.games.length
                    ? []
                    : preview.games.map((game) => game.index),
                )
              }
            >
              {selected.length === preview.games.length ? '取消全选' : '全选'}
            </button>
          </div>
          <ul className="nb-preview-list">
            {preview.games.map((game) => (
              <li key={game.index}>
                <label className="nb-check">
                  <input
                    type="checkbox"
                    disabled={busy}
                    checked={selected.includes(game.index)}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? [...selected, game.index]
                          : selected.filter((index) => index !== game.index),
                      )
                    }
                  />
                  <span>
                    <strong>
                      {game.white} — {game.black}
                    </strong>
                    <small>
                      {[
                        game.date,
                        game.result,
                        game.platform,
                        game.existing_id ? '已收录，将打开原谱' : null,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </small>
                  </span>
                </label>
                {!game.existing_id &&
                  game.possible_duplicates.length > 0 &&
                  selected.includes(game.index) && (
                    <label className="nb-field">
                      发现可能重复的棋谱
                      <select
                        value={choices[game.index] ?? ''}
                        disabled={busy}
                        required
                        onChange={(e) =>
                          setChoices({
                            ...choices,
                            [game.index]: e.target.value,
                          })
                        }
                      >
                        <option value="">请选择处理方式</option>
                        {game.possible_duplicates.map((id) => (
                          <option value={id} key={id}>
                            打开 {gameLabel(id)}
                          </option>
                        ))}
                        <option value="copy">另存为一盘新棋</option>
                      </select>
                    </label>
                  )}
              </li>
            ))}
          </ul>
          {error && (
            <p className="nb-error" role="alert">
              {error}
            </p>
          )}
        </form>
      ) : (
        <form
          id={formId}
          className="nb-form"
          onSubmit={(event) => void inspect(event)}
        >
          <div className="nb-segment" aria-label="导入来源">
            {(['pgn', 'url'] as const).map((type) => (
              <button
                aria-pressed={tab === type}
                type="button"
                key={type}
                disabled={busy}
                onClick={() => {
                  setTab(type);
                  setError('');
                }}
              >
                {type === 'pgn' ? 'PGN 棋谱' : '对局链接'}
              </button>
            ))}
          </div>
          {tab === 'pgn' ? (
            <>
              <label className="nb-field">
                选择 PGN 文件
                <input
                  type="file"
                  accept=".pgn,.txt,application/x-chess-pgn,text/plain"
                  disabled={busy || readingFile}
                  onChange={(e) => void load(e.target.files?.[0])}
                />
              </label>
              <label className="nb-field">
                PGN 棋谱
                <textarea
                  rows={6}
                  value={pgn}
                  disabled={busy || readingFile}
                  placeholder="粘贴一盘或多盘 PGN"
                  onChange={(e) => setPgn(e.target.value)}
                />
              </label>
            </>
          ) : (
            <>
              <label className="nb-field">
                对局链接
                <input
                  type="text"
                  inputMode="url"
                  autoCapitalize="none"
                  value={url}
                  disabled={busy}
                  required
                  autoComplete="off"
                  placeholder="Lichess 或 Chess.com 已结束的公开对局"
                  onChange={(e) => setUrl(e.target.value)}
                />
              </label>
              {isChessCom && (
                <details className="nb-details">
                  <summary>Chess.com 查找提示</summary>
                  <p>
                    若链接暂时查不到，可以补充一方用户名及对局结束月份，或直接导入
                    PGN。
                  </p>
                  <label className="nb-field">
                    棋手用户名（可选）
                    <input
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                    />
                  </label>
                  <label className="nb-field">
                    结束月份（可选）
                    <input
                      type="month"
                      value={month}
                      onChange={(e) => setMonth(e.target.value)}
                    />
                  </label>
                </details>
              )}
            </>
          )}
          {error && (
            <p className="nb-error" role="alert">
              {error}
            </p>
          )}
        </form>
      )}
    </NotebookDialog>
  );
}
