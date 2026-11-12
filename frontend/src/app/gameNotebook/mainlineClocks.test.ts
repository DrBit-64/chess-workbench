import { Chess, DEFAULT_POSITION } from 'chess.js';
import { expect, it } from 'vitest';
import { mainlineClocks } from './mainlineClocks';

function gameLine(moves: [string, string][], start = DEFAULT_POSITION) {
  const board = new Chess(start);
  return [
    {
      id: 'start',
      fen: start,
      san: null,
      ply: 0,
      is_mainline: true,
      comment: '',
    },
    ...moves.map(([san, comment], i) => {
      board.move(san);
      return {
        id: san,
        fen: board.fen(),
        san,
        ply: i + 1,
        is_mainline: true,
        comment,
      };
    }),
  ];
}

it('replays post-move clocks, including a missing stamp and time added at a control', () => {
  const nodes = gameLine([
    ['e4', '[%eval 0.23] [%clk 0:09:33]'],
    ['e5', '[%clk 0:09:58.50]'],
    ['Nf3', 'no clock supplied'],
    ['Nc6', '[%clk 1:02:00]'],
  ]);
  const clocks = mainlineClocks([...nodes].reverse(), '40/600:3600');
  expect(clocks?.get('start')).toEqual({ white: '10:00', black: '10:00' });
  expect(clocks?.get('e4')).toEqual({ white: '09:33', black: '10:00' });
  expect(clocks?.get('e5')).toEqual({ white: '09:33', black: '09:58.5' });
  expect(clocks?.get('Nc6')).toEqual({ white: undefined, black: '1:02:00' });
});

it('uses only source moves and never infers a fragment’s clock from its nominal time control', () => {
  const fragment = new Chess();
  fragment.move('e4');
  const nodes = gameLine([['c5', '[%clk 0:00:00]']], fragment.fen());
  const side = {
    ...nodes[1],
    id: 'variation',
    comment: '[%clk 9:99:99]',
    is_mainline: false,
  };
  const clocks = mainlineClocks([side, ...nodes], '300+3');
  expect(clocks?.get('start')).toEqual({ white: undefined, black: undefined });
  expect(clocks?.get('c5')).toEqual({ white: undefined, black: '00:00' });
  expect(clocks?.has('variation')).toBe(false);
  expect(mainlineClocks([nodes[0], side], '300+3')).toBeUndefined();
});
