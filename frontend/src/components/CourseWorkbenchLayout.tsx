import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  useRef,
  useState,
} from 'react';

type Widths = [number, number, number];
type Boundary = 0 | 1;

const STORAGE_KEY = 'chess-workbench.course-pane-widths';
const DEFAULT_WIDTHS: Widths = [380, 500, 520];
const MIN_WIDTHS: Widths = [220, 300, 320];
const LABELS = ['调整目录与棋盘宽度', '调整棋盘与内容宽度'];

function loadWidths(): Widths {
  try {
    const saved: unknown = JSON.parse(
      localStorage.getItem(STORAGE_KEY) ?? 'null',
    );
    if (
      Array.isArray(saved) &&
      saved.length === 3 &&
      saved.every(
        (width) =>
          typeof width === 'number' && Number.isFinite(width) && width > 0,
      )
    ) {
      return saved as Widths;
    }
  } catch {
    // Layout preferences are optional when browser storage is unavailable.
  }
  return DEFAULT_WIDTHS;
}

function saveWidths(widths: Widths) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(widths));
  } catch {
    // Resizing still works without persisting the preference.
  }
}

function resizeAdjacent(
  widths: Widths,
  boundary: Boundary,
  delta: number,
): Widths {
  const next: Widths = [...widths];
  const total = widths[boundary] + widths[boundary + 1];
  next[boundary] = Math.min(
    total - MIN_WIDTHS[boundary + 1],
    Math.max(MIN_WIDTHS[boundary], widths[boundary] + delta),
  );
  next[boundary + 1] = total - next[boundary];
  return next;
}

export function CourseWorkbenchLayout({
  children,
}: {
  children: [ReactNode, ReactNode, ReactNode];
}) {
  const grid = useRef<HTMLDivElement>(null);
  const [widths, setWidths] = useState<Widths>(loadWidths);
  const latestWidths = useRef(widths);
  const drag = useRef<{
    boundary: Boundary;
    pointerId: number;
    startX: number;
    measured: Widths;
    previous: Widths;
  }>();
  const [resizing, setResizing] = useState(false);

  function measureWidths(): Widths {
    return [0, 2, 4].map(
      (index) => grid.current!.children[index].getBoundingClientRect().width,
    ) as Widths;
  }

  function updateWidths(next: Widths) {
    latestWidths.current = next;
    setWidths(next);
  }

  function startDrag(
    event: ReactPointerEvent<HTMLDivElement>,
    boundary: Boundary,
  ) {
    if (event.button !== 0 || drag.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      boundary,
      pointerId: event.pointerId,
      startX: event.clientX,
      measured: measureWidths(),
      previous: latestWidths.current,
    };
    setResizing(true);
  }

  function moveDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const active = drag.current;
    if (!active || event.pointerId !== active.pointerId) return;
    updateWidths(
      resizeAdjacent(
        active.measured,
        active.boundary,
        event.clientX - active.startX,
      ),
    );
  }

  function finishDrag(
    event: ReactPointerEvent<HTMLDivElement>,
    cancelled = false,
  ) {
    const active = drag.current;
    if (!active || event.pointerId !== active.pointerId) return;
    if (cancelled) updateWidths(active.previous);
    else saveWidths(latestWidths.current);
    drag.current = undefined;
    setResizing(false);
  }

  function resetWidths() {
    updateWidths(DEFAULT_WIDTHS);
    saveWidths(DEFAULT_WIDTHS);
  }

  function separator(boundary: Boundary) {
    return (
      <div
        className="course-pane-resizer"
        role="separator"
        aria-label={LABELS[boundary]}
        aria-orientation="vertical"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(
          (widths[boundary] / (widths[boundary] + widths[boundary + 1])) * 100,
        )}
        tabIndex={0}
        title="拖动调整宽度；双击恢复默认；方向键微调"
        onPointerDown={(event) => startDrag(event, boundary)}
        onPointerMove={moveDrag}
        onPointerUp={(event) => finishDrag(event)}
        onPointerCancel={(event) => finishDrag(event, true)}
        onLostPointerCapture={(event) => finishDrag(event, true)}
        onDoubleClick={resetWidths}
        onKeyDown={(event) => {
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault();
          const delta =
            (event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 64 : 16);
          const next = resizeAdjacent(measureWidths(), boundary, delta);
          updateWidths(next);
          saveWidths(next);
        }}
      />
    );
  }

  return (
    <div
      ref={grid}
      className={`course-workbench-grid${resizing ? ' is-resizing' : ''}`}
      style={
        {
          '--course-left-width': `${widths[0]}fr`,
          '--course-board-width': `${widths[1]}fr`,
          '--course-reading-width': `${widths[2]}fr`,
        } as CSSProperties
      }
    >
      {children[0]}
      {separator(0)}
      {children[1]}
      {separator(1)}
      {children[2]}
    </div>
  );
}
