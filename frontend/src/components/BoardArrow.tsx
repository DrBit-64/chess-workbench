import type { Square } from 'chess.js';

import { squarePoint } from './boardAnnotations';

export function BoardArrow({
  from,
  to,
  color,
  orientation,
  source,
  brush,
  preview = false,
  shorten = false,
}: {
  from: Square;
  to: Square;
  color: string;
  orientation: 'white' | 'black';
  source: 'engine' | 'manual';
  brush?: string;
  preview?: boolean;
  shorten?: boolean;
}) {
  if (from === to) return null;
  const origin = squarePoint(from, orientation);
  const destination = squarePoint(to, orientation);
  const dx = destination.x - origin.x;
  const dy = destination.y - origin.y;
  const length = Math.hypot(dx, dy);

  // Chessground svg.ts: shaft 10/64 square, head 3 shaft-widths long and
  // 4 wide, refX 2.05, destination margin 10/64 (20/64 for converging arrows).
  // Unite the shaft and head so translucent fills are applied exactly once.
  const width = (10 / 64) * (preview ? 0.85 : 1);
  const radius = width / 2;
  const margin = (shorten && !preview ? 20 : 10) / 64;
  const tip = length - margin + 0.95 * width;
  const shoulder = tip - 3 * width;
  const head = 2 * width;
  const outline = [
    `M 0 ${-radius}`,
    `H ${shoulder} V ${-head}`,
    `L ${tip} 0 L ${shoulder} ${head}`,
    `V ${radius} H 0`,
    `A ${radius} ${radius} 0 0 1 0 ${-radius} Z`,
  ].join(' ');

  return (
    <path
      data-shape="arrow"
      data-source={source}
      data-from={from}
      data-to={to}
      data-brush={brush}
      d={outline}
      transform={`translate(${origin.x} ${origin.y}) rotate(${(Math.atan2(dy, dx) * 180) / Math.PI})`}
      fill={color}
      stroke="none"
      opacity={preview ? 0.9 : 1}
    />
  );
}
