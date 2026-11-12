import { Chessground } from '@lichess-org/chessground';
import { useLayoutEffect, useRef } from 'react';
import '@lichess-org/chessground/assets/chessground.base.css';
import '@lichess-org/chessground/assets/chessground.brown.css';
import '@lichess-org/chessground/assets/chessground.cburnett.css';

export function PositionThumbnail({
  fen,
  label,
}: {
  fen: string;
  label: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = host.current;
    if (!element) return;
    const board = Chessground(element, {
      fen,
      viewOnly: true,
      coordinates: false,
      drawable: { enabled: false, visible: false },
      animation: { enabled: false },
    });
    return () => board.destroy();
  }, [fen]);

  return (
    <div
      key={fen}
      ref={host}
      className="nb-diagram cg-wrap"
      role="img"
      aria-label={label}
      data-fen={fen}
    />
  );
}
