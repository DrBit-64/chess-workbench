import { useId } from 'react';

const symbols: Record<string, string> = {
  k: '♚',
  q: '♛',
  r: '♜',
  b: '♝',
  n: '♞',
  p: '♟',
};

// A passive diagram keeps a list of many positions scrollable on a phone.
export function PositionThumbnail({ fen }: { fen: string }) {
  const pattern = useId();
  const placement = fen.split(' ')[0];
  return (
    <svg
      className="nb-diagram"
      viewBox="0 0 80 80"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <pattern
          id={pattern}
          width="20"
          height="20"
          patternUnits="userSpaceOnUse"
        >
          <rect width="20" height="20" fill="#e6e8d2" />
          <path d="M10 0H20V10H10ZM0 10H10V20H0Z" fill="#809579" />
        </pattern>
      </defs>
      <rect width="80" height="80" fill={`url(#${pattern})`} />
      {placement.split('/').map((rank, row) => {
        let col = 0;
        return Array.from(rank).map((piece) => {
          if (/^[1-8]$/.test(piece)) {
            col += Number(piece);
            return null;
          }
          const file = col++;
          const white = piece.toLowerCase() !== piece;
          return (
            <text
              key={file}
              x={file * 10 + 5}
              y={row * 10 + 8.5}
              textAnchor="middle"
              fill={white ? '#fffef8' : '#222923'}
              stroke={white ? '#29342a' : '#111'}
              strokeWidth={white ? 0.65 : 0.12}
              paintOrder="stroke"
              fontSize="11"
              fontFamily="DejaVu Sans, Segoe UI Symbol, Noto Sans Symbols 2, serif"
            >
              {symbols[piece.toLowerCase()]}
            </text>
          );
        });
      })}
    </svg>
  );
}
