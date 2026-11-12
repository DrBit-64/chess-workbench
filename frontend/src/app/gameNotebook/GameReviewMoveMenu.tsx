import { useEffect, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { moveLabel, type ReviewNode } from './reviewTypes';

export type NotebookMoveAction =
  | 'promote_variation'
  | 'demote_variation'
  | 'make_mainline'
  | 'delete_subtree'
  | 'restore_path';

export interface MoveMenuAnchor {
  nodeId: string;
  x: number;
  y: number;
  trigger: HTMLElement;
}

export function GameReviewMoveMenu({
  anchor,
  node,
  canPromote,
  canDemote,
  isPreferredLine,
  onClose,
  onAction,
}: {
  anchor: MoveMenuAnchor;
  node: ReviewNode;
  canPromote: boolean;
  canDemote: boolean;
  isPreferredLine: boolean;
  onClose: () => void;
  onAction: (action: NotebookMoveAction) => void;
}) {
  const menu = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = menu.current!;
    const gap = 6;
    const rect = element.getBoundingClientRect();
    element.style.left =
      Math.max(gap, Math.min(anchor.x, window.innerWidth - rect.width - gap)) +
      'px';
    element.style.top =
      Math.max(
        gap,
        Math.min(anchor.y, window.innerHeight - rect.height - gap),
      ) + 'px';
    element
      .querySelector<HTMLButtonElement>('button:not(:disabled)')
      ?.focus({ preventScroll: true });
  }, [anchor]);
  useEffect(() => {
    function outside(event: Event) {
      if (event.target instanceof Node && !menu.current?.contains(event.target))
        onClose();
    }
    document.addEventListener('pointerdown', outside, true);
    document.addEventListener('focusin', outside);
    window.addEventListener('resize', onClose);
    return () => {
      document.removeEventListener('pointerdown', outside, true);
      document.removeEventListener('focusin', outside);
      window.removeEventListener('resize', onClose);
    };
  }, [onClose]);

  function choose(action: NotebookMoveAction) {
    onClose();
    anchor.trigger.focus({ preventScroll: true });
    onAction(action);
  }
  return createPortal(
    <div
      ref={menu}
      role="menu"
      aria-label={moveLabel(node) + ' 操作菜单'}
      className="nb-move-menu"
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          onClose();
          anchor.trigger.focus({ preventScroll: true });
          return;
        }
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key))
          return;
        event.preventDefault();
        event.stopPropagation();
        const buttons = Array.from(
          event.currentTarget.querySelectorAll<HTMLButtonElement>(
            'button:not(:disabled)',
          ),
        );
        const index = buttons.indexOf(
          document.activeElement as HTMLButtonElement,
        );
        let next: number;
        if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = buttons.length - 1;
        else
          next =
            (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) %
            buttons.length;
        buttons[next]?.focus();
      }}
    >
      <div className="nb-move-menu-title">{moveLabel(node)}</div>
      {node.hidden ? (
        <button
          type="button"
          role="menuitem"
          onClick={() => choose('restore_path')}
        >
          恢复这条线路
        </button>
      ) : (
        <>
          <button
            type="button"
            role="menuitem"
            disabled={!canPromote}
            onClick={() => choose('promote_variation')}
          >
            提升变招
          </button>
          <button
            type="button"
            role="menuitem"
            disabled={!canDemote}
            onClick={() => choose('demote_variation')}
          >
            降低变招
          </button>
          <button
            type="button"
            role="menuitem"
            disabled={isPreferredLine}
            onClick={() => choose('make_mainline')}
          >
            设为主线
          </button>
          <button
            type="button"
            role="menuitem"
            className="nb-move-menu-danger"
            onClick={() => choose('delete_subtree')}
          >
            从此处开始删除
          </button>
        </>
      )}
    </div>,
    document.fullscreenElement ?? document.body,
  );
}
