import { fireEvent, render, screen, within } from '@testing-library/react';
import { Chess } from 'chess.js';
import { expect, it, vi } from 'vitest';
import { GameReviewScore } from './GameReviewScore';
import type { ReviewNode } from './reviewTypes';

const root: ReviewNode = {
  id: 'root',
  parent_id: null,
  ply: 0,
  sort_order: 0,
  is_mainline: true,
  hidden: false,
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

it('pairs a Black-starting score and preserves the exact selectable positions in nested variations', () => {
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

it('edits the targeted branch, keeps sibling priorities bounded and confirms its exact subtree', () => {
  const played = child(root, 'Kf7'),
    alternative = child(root, 'Kd7', 1),
    reply = child(alternative, 'e3');
  const action = vi.fn(),
    select = vi.fn();
  const props = {
    root,
    visible: true,
    nodes: [root, played, alternative, reply],
    selectedId: reply.id,
    bookmarks: new Map([[reply.id, true]]),
    onSelect: select,
    onMoveAction: action,
  };
  const { rerender } = render(<GameReviewScore {...props} />);
  fireEvent.contextMenu(
    screen.getByRole('button', { name: '24... Kd7，分析变例' }),
    { clientX: 110, clientY: 82 },
  );
  const menu = screen.getByRole('menu', { name: '24... Kd7 操作菜单' });
  expect(
    (
      within(menu).getByRole('menuitem', {
        name: '降低变招',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(within(menu).getByRole('menuitem', { name: '提升变招' }));
  expect(action).toHaveBeenLastCalledWith('promote_variation', alternative);
  expect(select).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: '编辑当前棋步' }));
  const current = screen.getByRole('menu');
  expect(
    (
      within(current).getByRole('menuitem', {
        name: '提升变招',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  // A primary continuation inside an alternative can promote the entire path.
  fireEvent.click(within(current).getByRole('menuitem', { name: '设为主线' }));
  expect(action).toHaveBeenLastCalledWith('make_mainline', reply);

  fireEvent.keyDown(
    screen.getByRole('button', { name: '24... Kd7，分析变例' }),
    { key: 'F10', shiftKey: true },
  );
  fireEvent.click(screen.getByRole('menuitem', { name: '从此处开始删除' }));
  const dialog = screen.getByRole('dialog', { name: '删除棋步及后续变化' });
  expect(dialog.textContent).toContain('共 2 个棋步');
  expect(dialog.textContent).toContain('1 个局面收藏');
  expect(action).not.toHaveBeenCalledWith('delete_subtree', alternative);
  fireEvent.click(within(dialog).getByRole('button', { name: '确认删除' }));
  expect(action).toHaveBeenLastCalledWith('delete_subtree', alternative);

  const hiddenReply = { ...reply, hidden: true };
  rerender(
    <GameReviewScore
      {...props}
      nodes={[root, played, { ...alternative, hidden: true }, hiddenReply]}
    />,
  );
  expect(
    screen.queryByRole('button', { name: '24... Kd7，分析变例' }),
  ).toBeNull();
  expect(
    screen
      .getByRole('button', { name: '25. e3，分析变例，已收藏' })
      .getAttribute('aria-current'),
  ).toBe('step');
  fireEvent.click(screen.getByRole('button', { name: '恢复这条线路' }));
  expect(action).toHaveBeenLastCalledWith('restore_path', hiddenReply);
  rerender(<GameReviewScore {...props} selectedId={root.id} />);
  expect(
    (screen.getByRole('button', { name: '编辑当前棋步' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

it('shows the backed evaluation when an analysis variation is promoted into the displayed principal line', () => {
  const original = { ...child(root, 'Kf7'), sort_order: 1 };
  const promoted = { ...child(root, 'Kd7', 1), sort_order: 0 };
  const { container } = render(
    <GameReviewScore
      root={root}
      visible
      nodes={[root, original, promoted]}
      selectedId={promoted.id}
      bookmarks={new Map()}
      onSelect={() => {}}
      evaluations={
        new Map([
          [original.id, '#2'],
          [promoted.id, '+0.37'],
        ])
      }
    />,
  );
  expect(
    container.querySelector('.nb-notation-row .nb-notation-eval')?.textContent,
  ).toBe('+0.37');
  expect(
    container.querySelector('.nb-notation-variation .nb-notation-eval')
      ?.textContent,
  ).toBe('#2');
});
