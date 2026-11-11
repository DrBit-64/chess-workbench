import { useEffect, useId, useRef, type ReactNode } from 'react';
import './notebookCatalog.css';

export function NotebookDialog({
  title,
  onClose,
  children,
  footer,
  wide = false,
  busy = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  busy?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current!;
    const previous = document.activeElement;
    if (typeof element.showModal === 'function') element.showModal();
    else element.setAttribute('open', '');
    return () => {
      if (typeof element.close === 'function') element.close();
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus({ preventScroll: true });
    };
  }, []);

  return (
    <dialog
      ref={dialog}
      className={`nb-dialog${wide ? ' nb-dialog-wide' : ''}`}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <header className="nb-dialog-head">
        <h2 id={titleId}>{title}</h2>
        <button
          type="button"
          className="nb-btn"
          onClick={onClose}
          disabled={busy}
          aria-label="关闭弹窗"
        >
          关闭
        </button>
      </header>
      <div className="nb-dialog-body">{children}</div>
      {footer && (
        <footer className="nb-dialog-foot nb-actions">{footer}</footer>
      )}
    </dialog>
  );
}
