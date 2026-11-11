import {
  type ComponentProps,
  type PointerEvent,
  type ReactNode,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { flushSync } from 'react-dom';
import { Chessboard } from 'react-chessboard';

import { FAST_MOVE_ANIMATION_MS } from '../app/boardInteraction';
import { BoardArrow } from './BoardArrow';
import {
  BOARD_BRUSHES,
  type BoardShape,
  drawingBrush,
  squareAtPoint,
  squarePoint,
  toggleBoardShape,
} from './boardAnnotations';
import {
  MATERIAL_ROLES,
  type MaterialSide,
  boardMaterial,
} from './boardMaterial';
import { useBoardPointerMoves } from './useBoardPointerMoves';

type Props = Omit<ComponentProps<typeof Chessboard>, 'position'> & {
  position: string;
  fitReaderPane?: boolean;
  evaluationBar?: ReactNode;
};
type Drawing = BoardShape & { pointerId: number };

const GLYPHS = { q: '♛', r: '♜', b: '♝', n: '♞', p: '♟' };
const NAMES = { q: '后', r: '车', b: '象', n: '马', p: '兵' };

function MaterialRow({
  side,
  color,
  score,
}: {
  side: MaterialSide;
  color: 'white' | 'black';
  score: number;
}) {
  const label = color === 'white' ? '白方' : '黑方';
  const pieces = MATERIAL_ROLES.filter((role) => side[role] > 0);
  const description = pieces
    .map((role) => `${side[role]}${NAMES[role]}`)
    .join('、');
  return (
    <div
      className="board-material"
      role="group"
      data-color={color}
      aria-label={`${label}子力差：${description || '无多出棋子'}${score > 0 ? `，净多${score}分` : ''}`}
      title={`${label}${description ? `多出：${description}` : '无多出棋子'}；按双方同类棋子相抵计算`}
    >
      {pieces.map((role) => (
        <span className="board-material-group" key={role} aria-hidden="true">
          {Array.from({ length: side[role] }, (_, index) => (
            <span className="board-material-piece" key={index}>
              {GLYPHS[role]}
            </span>
          ))}
        </span>
      ))}
      {score > 0 ? (
        <span className="board-material-score">+{score}</span>
      ) : null}
    </div>
  );
}

export function WorkbenchBoard({
  position,
  fitReaderPane = false,
  evaluationBar,
  boardOrientation = 'white',
  customArrows = [],
  ...props
}: Props) {
  const surface = useRef<HTMLDivElement>(null);
  const [readerWidth, setReaderWidth] = useState(0);
  useLayoutEffect(() => {
    const element = surface.current;
    if (!fitReaderPane || !element) return;
    // The grid owns this square. Supply its new size before a resize paints
    // instead of letting the board's async auto-sizing display the old ranks.
    let width = element.clientWidth;
    setReaderWidth(width);
    const resize = () => {
      const next = element.clientWidth;
      if (next === width) return;
      width = next;
      flushSync(() => setReaderWidth(next));
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    window.addEventListener('resize', resize);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', resize);
    };
  }, [fitReaderPane]);

  const pointerMoves = useBoardPointerMoves({
    ...props,
    position,
    boardOrientation,
  });
  const [shapes, setShapes] = useState<BoardShape[]>([]);
  const [drawing, setDrawing] = useState<Drawing>();
  const gesture = useRef<Drawing>();
  const material = boardMaterial(position);
  const topColor = boardOrientation === 'white' ? 'black' : 'white';
  const manualShapes = [...shapes, ...(drawing ? [drawing] : [])];
  const arrowDestinations = new Map<string, Set<string>>();
  for (const [from, to] of customArrows) {
    if (from === to) continue;
    const sources = arrowDestinations.get(to) ?? new Set();
    sources.add(from);
    arrowDestinations.set(to, sources);
  }
  for (const shape of manualShapes) {
    if (shape.from === shape.to) continue;
    const sources = arrowDestinations.get(shape.to) ?? new Set();
    sources.add(shape.from);
    arrowDestinations.set(shape.to, sources);
  }

  useEffect(() => {
    setShapes([]);
    setDrawing(undefined);
    gesture.current = undefined;
  }, [position]);

  function squareAt(event: PointerEvent<HTMLDivElement>) {
    return squareAtPoint(
      event.clientX,
      event.clientY,
      event.currentTarget.getBoundingClientRect(),
      boardOrientation,
    );
  }

  function startDrawing(event: PointerEvent<HTMLDivElement>) {
    const isDrawing =
      event.button === 2 || (event.button === 0 && event.shiftKey);
    if (!isDrawing) {
      if (event.button === 0) {
        setShapes([]);
        pointerMoves.press(event);
      }
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const square = squareAt(event);
    if (!square) return;
    const next = {
      from: square,
      to: square,
      brush: drawingBrush(event),
      pointerId: event.pointerId,
    };
    gesture.current = next;
    setDrawing(next);
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function cancelDrawing() {
    gesture.current = undefined;
    setDrawing(undefined);
  }

  function finishDrawing(event: PointerEvent<HTMLDivElement>) {
    const current = gesture.current;
    if (!current || current.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    const square = squareAt(event);
    if (square)
      setShapes((previous) =>
        toggleBoardShape(previous, { ...current, to: square }),
      );
    cancelDrawing();
  }

  return (
    <div
      className="workbench-board"
      data-workbench-board={props.id ?? ''}
      data-can-drag={props.arePiecesDraggable !== false}
    >
      <MaterialRow
        color={topColor}
        side={material[topColor]}
        score={topColor === 'white' ? material.score : -material.score}
      />
      <div
        ref={surface}
        className="workbench-board-surface"
        role="group"
        tabIndex={0}
        aria-label="交互棋盘，可右键画圈或拖动绘制箭头"
        title="右键画圈或拖动箭头；Shift/Ctrl：红色，Alt：蓝色，组合：黄色；左键或 Esc 清除"
        onPointerDownCapture={startDrawing}
        onPointerMoveCapture={(event) => {
          const current = gesture.current;
          if (!current || current.pointerId !== event.pointerId) {
            pointerMoves.move(event);
            return;
          }
          const square = squareAt(event);
          setDrawing(square ? { ...current, to: square } : undefined);
        }}
        onPointerUpCapture={(event) => {
          finishDrawing(event);
          pointerMoves.end(event);
        }}
        onPointerCancel={(event) => {
          cancelDrawing();
          pointerMoves.end(event, true);
        }}
        onLostPointerCapture={(event) => {
          cancelDrawing();
          pointerMoves.end(event, true);
        }}
        onDragStartCapture={(event) => event.preventDefault()}
        onContextMenuCapture={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onMouseDownCapture={(event) => {
          if (event.button === 2 || event.shiftKey) event.stopPropagation();
        }}
        onMouseUpCapture={(event) => {
          if (event.button === 2 || event.shiftKey) event.stopPropagation();
        }}
        onClickCapture={(event) => {
          if (event.shiftKey || pointerMoves.suppressClick()) {
            event.preventDefault();
            event.stopPropagation();
          }
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            setShapes([]);
            cancelDrawing();
            pointerMoves.cancel();
          }
        }}
      >
        {(!fitReaderPane || readerWidth > 0) && (
          <Chessboard
            key={fitReaderPane ? 'reader' : 'workbench'}
            {...props}
            {...(fitReaderPane ? { boardWidth: readerWidth } : {})}
            position={position}
            boardOrientation={boardOrientation}
            animationDuration={
              pointerMoves.skipSlide
                ? 0
                : (props.animationDuration ?? FAST_MOVE_ANIMATION_MS)
            }
            arePiecesDraggable={false}
            areArrowsAllowed={false}
          />
        )}
        <svg className="board-drawings" viewBox="0 0 8 8" aria-hidden="true">
          {customArrows.map(([from, to, color], index) => (
            <BoardArrow
              key={`engine-${index}`}
              from={from}
              to={to}
              color={color ?? props.customArrowColor ?? BOARD_BRUSHES.green}
              orientation={boardOrientation}
              source="engine"
              shorten={(arrowDestinations.get(to)?.size ?? 0) > 1}
            />
          ))}
          {manualShapes.map((shape, index) => {
            const from = squarePoint(shape.from, boardOrientation);
            const preview = index === shapes.length;
            const color = BOARD_BRUSHES[shape.brush];
            if (shape.from === shape.to)
              return (
                <circle
                  key={index}
                  data-shape="circle"
                  data-from={shape.from}
                  data-brush={shape.brush}
                  cx={from.x}
                  cy={from.y}
                  r="0.45"
                  fill="none"
                  stroke={color}
                  strokeWidth="0.08"
                  opacity={preview ? 0.5 : 0.85}
                />
              );
            return (
              <BoardArrow
                key={`manual-${index}`}
                from={shape.from}
                to={shape.to}
                color={color}
                brush={shape.brush}
                orientation={boardOrientation}
                source="manual"
                preview={preview}
                shorten={(arrowDestinations.get(shape.to)?.size ?? 0) > 1}
              />
            );
          })}
        </svg>
      </div>
      {evaluationBar}
      <MaterialRow
        color={boardOrientation}
        side={material[boardOrientation]}
        score={boardOrientation === 'white' ? material.score : -material.score}
      />
    </div>
  );
}
