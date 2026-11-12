import { fireEvent, render, screen, within } from '@testing-library/react';
import { Chess } from 'chess.js';
import { expect, it, vi } from 'vitest';
import { GameReviewScore } from './GameReviewScore';
import type { ReviewNode } from './reviewTypes';

it('pairs a Black-starting score and preserves the exact selectable positions in nested variations', () => {
  const root: ReviewNode = {
    id: 'root',
    parent_id: null,
    ply: 0,
    sort_order: 0,
    is_mainline: true,
    fen: '4k3/8/8/8/8/8/4P3/4K3 b - - 0 24',
    san: null,
    uci: null,
    nags: [],
    starting_comment: '',
    comment: '',
    note: '',
    version: 1,
  };
  function child(parent: ReviewNode, san: string, sortOrder = 0): ReviewNode {
    const board = new Chess(parent.fen);
    const move = board.move(san);
    return {
      ...root,
      id: parent.id + '_' + san,
      parent_id: parent.id,
      ply: parent.ply + 1,
      sort_order: sortOrder,
      is_mainline: parent.is_mainline && sortOrder === 0,
      fen: board.fen(),
      san: move.san,
      uci: move.lan,
    };
  }
  const kf7 = child(root, 'Kf7'),
    kf2 = child(kf7, 'Kf2'),
    kf6 = child(kf2, 'Kf6');
  const kd7 = child(root, 'Kd7', 1),
    e3 = child(kd7, 'e3'),
    ke6 = child(e3, 'Ke6');
  const e4 = child(kd7, 'e4', 1),
    kd6 = child(e3, 'Kd6', 1);
  kf6.nags = [2];
  kd6.note = '比较王的位置';
  const select = vi.fn();
  const { container } = render(
    <GameReviewScore
      visible
      root={root}
      nodes={[root, kf7, kf2, kf6, kd7, e3, ke6, e4, kd6]}
      selectedId={kd6.id}
      bookmarks={new Map([[kd6.id, true]])}
      evaluations={
        new Map([
          [kf7.id, '0.0'],
          [kf6.id, '#3'],
        ])
      }
      onSelect={select}
    />,
  );
  const row24 = container.querySelector<HTMLElement>(
    '[data-move-number="24"]',
  )!;
  expect(within(row24).getAllByRole('button')).toHaveLength(1);
  expect(
    within(row24)
      .getByRole('button', { name: '24... Kf7' })
      .getAttribute('data-side'),
  ).toBe('black');
  expect(row24.querySelector('.nb-notation-eval')?.textContent).toBe('0.0');
  const row25 = container.querySelector<HTMLElement>(
    '[data-move-number="25"]',
  )!;
  const [white, black] = within(row25).getAllByRole('button');
  expect(white.getAttribute('aria-label')).toBe('25. Kf2');
  expect(white.querySelector('.nb-notation-eval')).toBeNull();
  expect(black.textContent).toContain('Kf6?');
  expect(black.querySelector('.nb-notation-eval')?.textContent).toBe('#3');
  expect(black.getAttribute('aria-description')).toContain('白方视角');

  const button = screen.getByRole('button', {
    name: '25... Kd6，分析变例，有棋步评语，已收藏',
  });
  expect(
    button.closest('.nb-notation-variation')?.getAttribute('data-depth'),
  ).toBe('2');
  expect(button.getAttribute('aria-current')).toBe('step');
  expect(
    container.querySelector('.nb-notation-variation[data-depth="1"]')
      ?.textContent,
  ).toContain('(24... Kd7');
  expect(container.querySelectorAll('[data-notebook-node]')).toHaveLength(9);
  fireEvent.click(button);
  expect(select).toHaveBeenCalledWith(kd6);
});
