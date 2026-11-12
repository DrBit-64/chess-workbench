import { Fragment, useEffect, useMemo, useRef, type ReactNode } from 'react';

import { MoveNotation } from '../MoveNotation';
import {
  buildScoreTreeLayout,
  type ScoreTreeVariation,
} from '../scoreTreeLayout';
import { moveLabel, type ReviewNode } from './reviewTypes';
import './gameReviewNotation.css';

interface MainlineRow {
  number: number;
  white?: ReviewNode;
  black?: ReviewNode;
}

function pairMainline(moves: ReviewNode[], rootFen: string) {
  const fields = rootFen.split(' ');
  let number = Number(fields[5]);
  let index = 0;
  const rows: MainlineRow[] = [];
  if (fields[1] === 'b' && moves.length) {
    rows.push({ number, black: moves[0] });
    number++;
    index = 1;
  }
  for (; index < moves.length; index += 2) {
    rows.push({ number, white: moves[index], black: moves[index + 1] });
    number++;
  }
  return rows;
}

export function GameReviewScore({
  visible,
  nodes,
  root,
  selectedId,
  bookmarks,
  evaluations,
  onSelect,
}: {
  visible: boolean;
  nodes: ReviewNode[];
  root: ReviewNode;
  selectedId: string;
  bookmarks: ReadonlyMap<string, unknown>;
  evaluations?: ReadonlyMap<string, string>;
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
  const rows = useMemo(
    () => pairMainline(score.mainline, root.fen),
    [score, root.fen],
  );
  const list = useRef<HTMLElement>(null);

  useEffect(() => {
    const nav = list.current;
    if (!visible || !nav) return;
    const column = nav.closest<HTMLElement>('.game-review-score-column');
    const active = nav.querySelector<HTMLElement>('[aria-current="step"]');
    if (!active) return;

    const reveal = () => {
      // Rotation can transfer scrolling from the entire engine/score column to
      // the score alone. An overflow:hidden column still retains its old offset.
      const scroller =
        getComputedStyle(nav).overflowY === 'visible' ? (column ?? nav) : nav;
      if (!scroller.clientHeight) return;
      if (
        column &&
        scroller === nav &&
        getComputedStyle(column).overflowY === 'hidden'
      )
        column.scrollTop = 0;
      const bounds = scroller.getBoundingClientRect();
      const item = active.getBoundingClientRect();
      if (item.top < bounds.top || item.bottom > bounds.bottom)
        scroller.scrollTop += item.top - bounds.top - scroller.clientHeight / 3;
    };
    reveal();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(reveal);
    observer.observe(nav);
    if (column) observer.observe(column);
    return () => observer.disconnect();
  }, [selectedId, visible]);

  function moveButton(node: ReviewNode, prefix = '') {
    const starred = bookmarks.has(node.id);
    const current = selectedId === node.id;
    const label = moveLabel(node);
    const scoreText =
      node.san && node.is_mainline ? evaluations?.get(node.id) : undefined;
    return (
      <button
        type="button"
        className={node.san ? 'nb-notation-move' : 'nb-notation-start'}
        data-notebook-node={node.id}
        data-side={
          node.san
            ? node.fen.split(' ')[1] === 'w'
              ? 'black'
              : 'white'
            : undefined
        }
        aria-current={current ? 'step' : undefined}
        aria-label={
          label +
          (node.is_mainline ? '' : '，分析变例') +
          (node.note ? '，有棋步评语' : '') +
          (starred ? '，已收藏' : '')
        }
        aria-description={
          scoreText ? `走后评分（白方视角）${scoreText}` : undefined
        }
        onClick={() => onSelect(node)}
      >
        <span className="nb-notation-san">
          {prefix && (
            <span className="nb-notation-inline-number">{prefix} </span>
          )}
          {node.san ? (
            <MoveNotation san={node.san} nags={node.nags} active={current} />
          ) : (
            '起始局面'
          )}
          {node.note && (
            <span
              className="nb-notation-mark"
              aria-hidden="true"
              title="有棋步评语"
            >
              ✎
            </span>
          )}
          {starred && (
            <span
              className="nb-notation-mark"
              aria-hidden="true"
              title="已收藏此局面"
            >
              ★
            </span>
          )}
        </span>
        {scoreText && (
          <span
            className="nb-notation-eval"
            title={`走后评分（白方视角）${scoreText}`}
          >
            {scoreText}
          </span>
        )}
      </button>
    );
  }

  function variation(line: ScoreTreeVariation<ReviewNode>): ReactNode {
    let needsNumber = true;
    return (
      <span
        className="nb-notation-variation"
        data-depth={line.depth}
        data-inline={line.presentation === 'parenthetical'}
        key={line.key}
      >
        <span aria-hidden="true">(</span>
        {line.moves.map((node, index) => {
          // Siblings of the first move are already being rendered by the parent line.
          const alternatives =
            index > 0
              ? score.variationsByParent.get(node.parent_id)
              : undefined;
          const number = moveLabel(node).split(' ')[0];
          const prefix = needsNumber || !number.endsWith('...') ? number : '';
          needsNumber = Boolean(alternatives?.length);
          return (
            <Fragment key={node.id}>
              {index > 0 && ' '}
              {moveButton(node, prefix)}
              {alternatives?.map(variation)}
            </Fragment>
          );
        })}
        <span aria-hidden="true">)</span>
      </span>
    );
  }

  return (
    <nav
      ref={list}
      className="game-review-score-list nb-notation"
      aria-label="对局棋谱"
    >
      {moveButton(root)}
      {rows.map(({ number, white, black }) => (
        <Fragment key={number}>
          <div className="nb-notation-row" data-move-number={number}>
            <span className="nb-notation-number" aria-hidden="true">
              {number}
            </span>
            {white ? (
              moveButton(white)
            ) : (
              <span className="nb-notation-empty" aria-hidden="true">
                …
              </span>
            )}
            {black && moveButton(black)}
          </div>
          {white &&
            score.variationsByParent.get(white.parent_id)?.map(variation)}
          {black &&
            score.variationsByParent.get(black.parent_id)?.map(variation)}
        </Fragment>
      ))}
    </nav>
  );
}
