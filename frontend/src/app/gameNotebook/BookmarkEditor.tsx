import { useId, useState, type FormEvent } from 'react';
import { NotebookDialog } from './NotebookDialog';

export type BookmarkFields = { title: string; note: string; tags: string[] };

export function BookmarkEditor({
  initial,
  suggestedTags,
  onSave,
  onClose,
}: {
  initial: BookmarkFields;
  suggestedTags: string[];
  onSave: (value: BookmarkFields) => Promise<void>;
  onClose: () => void;
}) {
  const [opening] = useState(initial);
  const [title, setTitle] = useState(initial.title);
  const [note, setNote] = useState(initial.note);
  const [tags, setTags] = useState(initial.tags);
  const [tagInput, setTagInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const tagId = useId();
  const formId = useId();

  const changedElsewhere =
    opening.title !== initial.title ||
    opening.note !== initial.note ||
    opening.tags.join('\n') !== initial.tags.join('\n');
  const suggestions = suggestedTags
    .filter((tag) => !tags.includes(tag) && tag.includes(tagInput.trim()))
    .slice(0, 8);

  function withTag() {
    const tag = tagInput.trim();
    return !tag || tags.includes(tag) ? tags : [...tags, tag];
  }
  function addTag() {
    setTags(withTag());
    setTagInput('');
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (withTag().length > 64) {
      setError('每个局面最多可添加 64 个标签。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await onSave({ title: title.trim(), note, tags: withTag() });
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '保存失败，请重试');
    } finally {
      setBusy(false);
    }
  }

  return (
    <NotebookDialog
      title="编辑收藏"
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button
            className="nb-btn primary"
            form={formId}
            type="submit"
            disabled={busy}
          >
            {busy ? '保存中…' : '保存'}
          </button>
          <button
            className="nb-btn"
            type="button"
            disabled={busy}
            onClick={onClose}
          >
            取消
          </button>
        </>
      }
    >
      {changedElsewhere && (
        <details className="nb-latest" open>
          <summary>其他设备保存的最新内容</summary>
          <p>
            <b>标题</b> {initial.title || '（空）'}
          </p>
          <p>
            <b>局面评语</b> {initial.note || '（空）'}
          </p>
          <p>
            <b>标签</b> {initial.tags.join('、') || '（无）'}
          </p>
        </details>
      )}
      <form
        id={formId}
        onSubmit={(event) => void save(event)}
        className="nb-form"
      >
        <label className="nb-field">
          标题
          <input
            maxLength={200}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="留空时使用对局和回合"
          />
        </label>
        <label className="nb-field">
          局面评语
          <textarea
            rows={4}
            maxLength={100000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="以后想回看什么？"
          />
        </label>
        <div className="nb-field">
          <label htmlFor={tagId}>标签</label>
          {tags.length > 0 && (
            <div className="nb-tags" aria-label="已选标签">
              {tags.map((tag) => (
                <button
                  className="nb-chip selected"
                  type="button"
                  key={tag}
                  aria-label={`移除标签 ${tag}`}
                  onClick={() => setTags(tags.filter((value) => value !== tag))}
                >
                  {tag} ×
                </button>
              ))}
            </div>
          )}
          <div className="nb-input-action">
            <input
              id={tagId}
              value={tagInput}
              maxLength={80}
              aria-label="添加标签"
              placeholder="输入或选择标签"
              list={tagId + '-suggestions'}
              onChange={(event) => setTagInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  addTag();
                }
              }}
            />
            <datalist id={tagId + '-suggestions'}>
              {suggestedTags
                .filter((tag) => !tags.includes(tag))
                .map((tag) => (
                  <option key={tag} value={tag} />
                ))}
            </datalist>
            <button
              type="button"
              className="nb-btn"
              onClick={addTag}
              disabled={!tagInput.trim()}
            >
              添加
            </button>
          </div>
          {suggestions.length > 0 && (
            <div className="nb-tags" aria-label="可用标签">
              {suggestions.map((tag) => (
                <button
                  type="button"
                  className="nb-chip"
                  key={tag}
                  onClick={() => {
                    setTags([...tags, tag]);
                    setTagInput('');
                  }}
                >
                  {tag}
                </button>
              ))}
            </div>
          )}
        </div>
        {error && (
          <p className="nb-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </NotebookDialog>
  );
}
