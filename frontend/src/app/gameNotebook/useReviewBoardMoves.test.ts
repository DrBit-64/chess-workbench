import { act, renderHook } from '@testing-library/react';
import { Chess, DEFAULT_POSITION } from 'chess.js';
import { expect, it, vi } from 'vitest';

import { bookmarkContinuation } from './practiceLines';
import type { ReviewNode } from './reviewTypes';
import { useReviewBoardMoves } from './useReviewBoardMoves';

const root: ReviewNode = {
  id: 'root',
  parent_id: null,
  ply: 0,
  sort_order: 0,
  is_mainline: true,
  hidden: false,
  fen: DEFAULT_POSITION,
  san: null,
  uci: null,
  nags: [],
  starting_comment: '',
  comment: '',
  note: '',
  version: 1,
};
const source = new Chess();
const first = source.move('e4');
const e4: ReviewNode = {
  ...root,
  id: 'e4',
  parent_id: root.id,
  ply: 1,
  san: first.san,
  uci: first.lan,
  fen: first.after,
};

it('follows a stored move with recording off and navigates temporary clicks and drags without writing them', () => {
  const select = vi.fn();
  const record = vi.fn(() => Promise.resolve());
  const children = new Map([[root.id, [e4]]]);
  const { result } = renderHook(() =>
    useReviewBoardMoves(root, children, false, select, record),
  );
  expect(result.current.recording).toBe(true);
  act(() => result.current.setRecordingMode(false));
  act(() => result.current.click('e2'));
  expect(result.current.selected).toBe('e2');
  act(() => result.current.click('e4'));
  expect(select).toHaveBeenCalledWith(e4);
  act(() => {
    expect(result.current.play('d2', 'd5')).toBe(false);
  });
  act(() => {
    expect(result.current.play('d2', 'd4')).toBe(true);
  });
  const firstTrial = result.current.fen;
  act(() => {
    result.current.play('c7', 'c5');
  });
  const lastTrial = result.current.fen;
  act(() => {
    result.current.step('previous');
  });
  expect(result.current.fen).toBe(firstTrial);
  act(() => {
    result.current.step('last');
  });
  expect(result.current.fen).toBe(lastTrial);
  act(() => {
    result.current.step('first');
  });
  expect(result.current.fen).toBe(root.fen);
  expect(record).not.toHaveBeenCalled();
  act(() => result.current.setRecordingMode(true));
  expect(result.current.trial).toBeUndefined();
});

it('allows underpromotion and rolls back the pending preview when persistence finishes without selection', async () => {
  const parent = { ...root, fen: '8/P6k/8/8/8/8/7K/8 w - - 0 1' };
  let finish!: () => void;
  const record = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const { result } = renderHook(() =>
    useReviewBoardMoves(parent, new Map(), false, vi.fn(), record),
  );
  act(() => {
    result.current.play('a7', 'a8');
  });
  expect(result.current.promotion).toMatchObject({ from: 'a7', to: 'a8' });
  expect(record).not.toHaveBeenCalled();
  act(() => {
    result.current.play('a7', 'a8', 'n');
  });
  expect(record).toHaveBeenCalledWith(parent, 'a7a8n');
  expect(result.current.fen).toMatch(/^N7\//);
  expect(result.current.enabled).toBe(false);
  await act(async () => {
    finish();
  });
  expect(result.current.fen).toBe(parent.fen);
});

it('uses the actual continuation for bookmark answers despite promoted alternatives or a hidden played move', () => {
  const alternative = { ...e4, id: 'd4', uci: 'd2d4', is_mainline: false };
  const afterEnd = { ...alternative, id: 'e5', parent_id: 'e4', uci: 'e7e5' };
  const nodes = [
    root,
    alternative,
    { ...e4, hidden: true, sort_order: 1 },
    afterEnd,
  ];
  expect(bookmarkContinuation(nodes, root.id, [])).toEqual(['e2e4']);
  expect(
    bookmarkContinuation(nodes, root.id, [{ node_id: alternative.id }]),
  ).toEqual(['d2d4']);
  expect(bookmarkContinuation(nodes, e4.id, [])).toEqual([]);
});
