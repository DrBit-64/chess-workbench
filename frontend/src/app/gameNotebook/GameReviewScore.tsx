import { Fragment, useEffect, useMemo, useRef, type ReactNode } from 'react';

import { MoveNotation } from '../MoveNotation';
import { buildScoreTreeLayout } from '../scoreTreeLayout';
import { moveLabel, type ReviewNode } from './reviewTypes';

export function GameReviewScore({
  visible,
  nodes,
  root,
  selectedId,
  bookmarks,
  onSelect,
}: {
  visible: boolean;
  nodes: ReviewNode[];
  root: ReviewNode;
  selectedId: string;
  bookmarks: ReadonlyMap<string, unknown>;
  onSelect: (node: ReviewNode) => void;
}) {
  const score = useMemo(
    () =>
      buildScoreTreeLayout(nodes, root.id, (node) => ({
        id: node.id,
        parentId: node.parent_id ?? null,
        order: node.sort_order,
      })),
    [nodes, root.id],
  );
  const list = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!visible || !list.current) return;
    const scroller =
      getComputedStyle(list.current).overflowY === 'visible'
        ? list.current.closest<HTMLElement>('.game-review-inspector')
        : list.current;
    const active = scroller?.querySelector<HTMLElement>(
      '[aria-current="step"]',
    );
    // Keep the score in sync on long games without scrolling the document or board.
    if (!scroller || !active || !scroller.clientHeight) return;
    const bounds = scroller.getBoundingClientRect();
    const item = active.getBoundingClientRect();
    const tabs =
      scroller !== list.current &&
      scroller.querySelector<HTMLElement>('.game-review-tabs');
    const inset =
      tabs && getComputedStyle(tabs).position === 'sticky'
        ? tabs.offsetHeight
        : 0;
    if (item.top < bounds.top + inset || item.bottom > bounds.bottom)
      scroller.scrollTop += item.top - bounds.top - scroller.clientHeight / 3;
  }, [selectedId, visible]);

  function moveButton(node: ReviewNode) {
    const starred = bookmarks.has(node.id);
    const current = selectedId === node.id;
    const label = moveLabel(node);
    return (
      <button
        type="button"
        className="game-review-move"
        data-notebook-node={node.id}
        aria-current={current ? 'step' : undefined}
        aria-label={
          label +
          (node.is_mainline ? '' : '，分析变例') +
          (node.note ? '，有棋步评语' : '') +
          (starred ? '，已收藏' : '')
        }
        onClick={() => onSelect(node)}
      >
        {node.san ? (
          <>
            <span className="game-review-move-number">
              {label.split(' ')[0]}
            </span>
            <MoveNotation san={node.san} nags={node.nags} active={current} />
          </>
        ) : (
          '起始局面'
        )}
        {node.note && (
          <span
            className="game-review-note-mark"
            aria-hidden="true"
            title="有棋步评语"
          >
            ✎
          </span>
        )}
        {starred && (
          <span aria-hidden="true" title="已收藏此局面">
            ★
          </span>
        )}
      </button>
    );
  }

  function renderLine(line: ReviewNode[], variation: boolean): ReactNode {
    return line.map((node, index) => {
      // The first move of an alternative shares its parent with the main move:
      // the sibling variations have already been shown by that parent.
      const alternatives =
        variation && index === 0
          ? undefined
          : score.variationsByParent.get(node.parent_id ?? null);
      return (
        <Fragment key={node.id}>
          {moveButton(node)}
          {alternatives?.map((alternative) => (
            <div key={alternative.key} className="game-review-variation">
              <span className="game-review-variation-label">变例</span>
              {renderLine(alternative.moves, true)}
            </div>
          ))}
        </Fragment>
      );
    });
  }

  return (
    <nav ref={list} className="game-review-score-list" aria-label="对局棋谱">
      <div className="game-review-score-flow">
        {moveButton(root)}
        {renderLine(score.mainline, false)}
      </div>
    </nav>
  );
}
