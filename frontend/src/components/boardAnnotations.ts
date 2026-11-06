import type { Square } from 'chess.js';

export const BOARD_BRUSHES = {
  green: '#15781b',
  red: '#882020',
  blue: '#003088',
  yellow: '#e68f00',
} as const;

export type BoardBrush = keyof typeof BOARD_BRUSHES;
export type BoardShape = { from: Square; to: Square; brush: BoardBrush };

// Chessground draw.ts: Shift/Ctrl + right = red, Alt/Meta = blue, both = yellow.
export function drawingBrush(event: {
  button: number;
  shiftKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  metaKey: boolean;
  getModifierState?: (key: 'AltGraph') => boolean;
}): BoardBrush {
  const red = event.button === 2 && (event.shiftKey || event.ctrlKey);
  const blue =
    event.altKey || event.metaKey || event.getModifierState?.('AltGraph');
  return blue ? (red ? 'yellow' : 'blue') : red ? 'red' : 'green';
}

export function toggleBoardShape(
  shapes: BoardShape[],
  next: BoardShape,
): BoardShape[] {
  const previous = shapes.find(
    (shape) => shape.from === next.from && shape.to === next.to,
  );
  const rest = shapes.filter((shape) => shape !== previous);
  return previous?.brush === next.brush ? rest : [...rest, next];
}

export function squarePoint(square: Square, orientation: 'white' | 'black') {
  const file = square.charCodeAt(0) - 97;
  const rank = Number(square[1]) - 1;
  return orientation === 'white'
    ? { x: file + 0.5, y: 7.5 - rank }
    : { x: 7.5 - file, y: rank + 0.5 };
}

export function squareAtPoint(
  x: number,
  y: number,
  bounds: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>,
  orientation: 'white' | 'black',
): Square | undefined {
  const col = Math.floor(((x - bounds.left) / bounds.width) * 8);
  const row = Math.floor(((y - bounds.top) / bounds.height) * 8);
  if (!(col >= 0 && col < 8 && row >= 0 && row < 8)) return undefined;
  const file = orientation === 'white' ? col : 7 - col;
  const rank = orientation === 'white' ? 8 - row : row + 1;
  return `${String.fromCharCode(97 + file)}${rank}` as Square;
}
