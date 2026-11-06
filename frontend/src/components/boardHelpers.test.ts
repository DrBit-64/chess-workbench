import { describe, expect, it } from 'vitest';

import {
  drawingBrush,
  squareAtPoint,
  squarePoint,
  toggleBoardShape,
} from './boardAnnotations';
import { boardMaterial } from './boardMaterial';

describe('board material', () => {
  it('cancels equal roles and scores an uneven exchange from a diagram FEN', () => {
    const material = boardMaterial('r3k3/8/8/8/8/8/1P6/1N2K3 w - - 0 1');
    expect(material.white).toEqual({ q: 0, r: 0, b: 0, n: 1, p: 1 });
    expect(material.black).toEqual({ q: 0, r: 1, b: 0, n: 0, p: 0 });
    expect(material.score).toBe(-1);
  });

  it('counts promoted pieces without assuming the starting army', () => {
    const material = boardMaterial('3qk3/8/8/8/8/8/8/QQ2K3 w - - 0 1');
    expect(material.white.q).toBe(1);
    expect(material.black.q).toBe(0);
    expect(material.score).toBe(9);
  });
});

describe('board annotations', () => {
  it('toggles the same shape and replaces its color', () => {
    const circle = { from: 'e4', to: 'e4', brush: 'green' } as const;
    const marked = toggleBoardShape([], circle);
    expect(toggleBoardShape(marked, circle)).toEqual([]);
    expect(toggleBoardShape(marked, { ...circle, brush: 'red' })).toEqual([
      { ...circle, brush: 'red' },
    ]);
  });

  it('uses Chessground modifier colors', () => {
    const event = {
      button: 2,
      shiftKey: false,
      ctrlKey: false,
      altKey: false,
      metaKey: false,
    };
    expect(drawingBrush(event)).toBe('green');
    expect(drawingBrush({ ...event, shiftKey: true })).toBe('red');
    expect(drawingBrush({ ...event, altKey: true })).toBe('blue');
    expect(drawingBrush({ ...event, ctrlKey: true, altKey: true })).toBe(
      'yellow',
    );
  });

  it('maps board coordinates in both orientations and rejects release outside the board', () => {
    const bounds = { left: 100, top: 50, width: 800, height: 800 };
    expect(squareAtPoint(150, 100, bounds, 'white')).toBe('a8');
    expect(squareAtPoint(150, 100, bounds, 'black')).toBe('h1');
    expect(squarePoint('e4', 'white')).toEqual({ x: 4.5, y: 4.5 });
    expect(squarePoint('e4', 'black')).toEqual({ x: 3.5, y: 3.5 });
    expect(squareAtPoint(901, 500, bounds, 'white')).toBeUndefined();
  });
});
