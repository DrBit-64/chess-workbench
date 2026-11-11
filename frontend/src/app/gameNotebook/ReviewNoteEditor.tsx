import { Alert, Button, Input } from 'antd';
import { NotebookDialog } from './NotebookDialog';
import { useState } from 'react';

import { ApiError } from '../../logic/api/client';

export interface ReviewNoteTarget {
  kind: 'move' | 'summary';
  nodeId?: string;
  text: string;
  version: number;
  position: string;
}

export function ReviewNoteEditor({
  target,
  onClose,
  onSave,
  reload,
}: {
  target: ReviewNoteTarget;
  onClose: () => void;
  onSave: (text: string, version: number) => Promise<void>;
  reload: () => Promise<{ text: string; version: number } | undefined>;
}) {
  const [draft, setDraft] = useState(target.text);
  const [baseline, setBaseline] = useState({
    text: target.text,
    version: target.version,
  });
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const label = target.kind === 'move' ? '棋步评语' : '整盘总结';
  const deleteLabel = target.kind === 'move' ? '删除评语' : '删除总结';

  async function save(text: string) {
    setPending(true);
    setError('');
    try {
      await onSave(text, baseline.version);
      onClose();
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        const latest = await reload().catch(() => undefined);
        if (latest) {
          setBaseline(latest);
          setError(
            '另一处已更新这条笔记。请对照最新内容，再决定是否保存你的草稿。',
          );
        } else
          setError('另一处已更新这条笔记。暂时无法读取最新版，可以稍后重试。');
      } else
        setError(
          reason instanceof Error ? reason.message : '保存失败，请重试。',
        );
    } finally {
      setPending(false);
      setConfirmClear(false);
    }
  }

  return (
    <NotebookDialog title={label} busy={pending} onClose={onClose}>
      <p className="game-review-caption">{target.position}</p>
      <Input.TextArea
        aria-label={label}
        autoFocus
        rows={5}
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          setConfirmClear(false);
        }}
      />
      {error && <Alert type="error" showIcon title={error} />}
      {baseline.version !== target.version && (
        <p className="game-review-prose">
          <strong>已保存的内容</strong>
          <br />
          {baseline.text || '（空）'}
        </p>
      )}
      <div className="game-review-note-footer">
        {baseline.text && (
          <Button
            danger
            disabled={pending}
            onClick={() =>
              confirmClear ? void save('') : setConfirmClear(true)
            }
          >
            {confirmClear ? '确认删除' : deleteLabel}
          </Button>
        )}
        <Button disabled={pending} onClick={onClose}>
          取消
        </Button>
        <Button
          type="primary"
          loading={pending}
          disabled={draft === baseline.text}
          onClick={() => void save(draft)}
        >
          保存
        </Button>
      </div>
    </NotebookDialog>
  );
}
