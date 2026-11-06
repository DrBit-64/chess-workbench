import { Chess, type Square } from 'chess.js';
import {
  type ComponentProps,
  type PointerEvent,
  useEffect,
  useRef,
} from 'react';
import type { Chessboard } from 'react-chessboard';

import { squareAtPoint } from './boardAnnotations';

type BoardProps = ComponentProps<typeof Chessboard>;
type Piece = Parameters<NonNullable<BoardProps['onPieceDragBegin']>>[0];
type Press = {
  pointerId: number;
  from: Square;
  piece: Piece;
  x: number;
  y: number;
  started: boolean;
  origin: HTMLElement;
  preview?: HTMLElement;
};

// Chessground drag.ts/state.ts: select on press, start a drag after 3px,
// follow the pointer without a transition, and leave a 30% origin ghost.
export function useBoardPointerMoves(props: BoardProps & { position: string }) {
  const active = useRef<Press>();
  const frame = useRef<number>();
  const handledClick = useRef(false);
  const droppedPlacement = useRef<string>();
  const orientation = props.boardOrientation ?? 'white';

  function clearPreview() {
    if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    frame.current = undefined;
    const current = active.current;
    current?.origin.classList.remove('workbench-piece-origin');
    current?.preview?.remove();
    active.current = undefined;
  }

  useEffect(() => {
    if (droppedPlacement.current !== props.position.split(' ')[0])
      droppedPlacement.current = undefined;
    return clearPreview;
  }, [props.position, orientation]);

  function squareAt(event: PointerEvent<HTMLDivElement>) {
    return squareAtPoint(
      event.clientX,
      event.clientY,
      event.currentTarget.getBoundingClientRect(),
      orientation,
    );
  }

  function press(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || active.current) return;
    const square = squareAt(event);
    if (!square) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.focus({ preventScroll: true });
    handledClick.current = true;
    droppedPlacement.current = undefined;
    const game = new Chess(
      props.position === 'start' ? undefined : props.position,
    );
    const value = game.get(square);
    const piece = value
      ? (`${value.color}${value.type.toUpperCase()}` as Piece)
      : undefined;

    // Dispatch the existing page selection/move handler immediately. Do not
    // dispatch again on mouseup, or selecting a piece would toggle it off.
    props.onSquareClick?.(square, piece);
    if (piece) props.onPieceClick?.(piece, square);
    const origin = event.currentTarget.querySelector<HTMLElement>(
      `[data-square="${square}"] [data-piece="${piece}"]`,
    );
    if (
      !piece ||
      value?.color !== game.turn() ||
      props.arePiecesDraggable === false ||
      props.isDraggablePiece?.({ piece, sourceSquare: square }) === false ||
      !origin
    )
      return;

    active.current = {
      pointerId: event.pointerId,
      from: square,
      piece,
      x: event.clientX,
      y: event.clientY,
      origin,
      started: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function move(event: PointerEvent<HTMLDivElement>) {
    const current = active.current;
    if (!current || event.pointerId !== current.pointerId) return;
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - bounds.left - bounds.width / 16;
    const y = event.clientY - bounds.top - bounds.height / 16;
    if (!current.started) {
      if (Math.hypot(event.clientX - current.x, event.clientY - current.y) < 3)
        return;
      current.started = true;
      const preview = current.origin.cloneNode(true) as HTMLElement;
      preview.classList.add('workbench-piece-preview');
      preview.setAttribute('aria-hidden', 'true');
      preview.style.width = `${event.currentTarget.getBoundingClientRect().width / 8}px`;
      preview.style.height = preview.style.width;
      preview.style.opacity = '1';
      preview.style.transition = 'none';
      preview.style.cursor = 'grabbing';
      preview.style.transform = `translate(${x}px, ${y}px)`;
      current.preview = preview;
      current.origin.classList.add('workbench-piece-origin');
      event.currentTarget.appendChild(preview);
      props.onPieceDragBegin?.(current.piece, current.from);
    }
    if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      if (current.preview)
        current.preview.style.transform = `translate(${x}px, ${y}px)`;
      frame.current = undefined;
    });
  }

  function end(event: PointerEvent<HTMLDivElement>, cancelled = false) {
    const current = active.current;
    if (!current || event.pointerId !== current.pointerId) return;
    const target = squareAt(event);
    clearPreview();
    if (current.started) {
      props.onPieceDragEnd?.(current.piece, current.from);
      if (!cancelled && target && target !== current.from) {
        // A dragged piece is already at its destination. Suppress only this
        // move's slide; navigation and the opponent's next move still animate.
        const game = new Chess(
          props.position === 'start' ? undefined : props.position,
        );
        try {
          game.move({ from: current.from, to: target, promotion: 'q' });
          droppedPlacement.current = game.fen().split(' ')[0];
        } catch {
          droppedPlacement.current = undefined;
        }
        props.onPieceDrop?.(current.from, target, current.piece);
      }
    }
  }

  return {
    press,
    move,
    end,
    cancel() {
      const current = active.current;
      clearPreview();
      if (current?.started) props.onPieceDragEnd?.(current.piece, current.from);
    },
    suppressClick() {
      const handled = handledClick.current;
      handledClick.current = false;
      return handled;
    },
    skipSlide: droppedPlacement.current === props.position.split(' ')[0],
  };
}
