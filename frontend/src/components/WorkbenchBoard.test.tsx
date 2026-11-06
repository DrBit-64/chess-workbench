import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WorkbenchBoard } from './WorkbenchBoard';

vi.mock('react-chessboard', () => ({
  Chessboard: ({
    customArrows,
    animationDuration,
  }: {
    customArrows?: unknown[];
    animationDuration: number;
  }) => (
    <>
      <output data-testid="engine-arrows">
        {JSON.stringify(customArrows)}
      </output>
      <output data-testid="animation-duration">{animationDuration}</output>
      <div data-square="b1">
        <div data-piece="wN" />
      </div>
    </>
  ),
}));

const fen = 'r3k3/8/8/8/8/8/1P6/1N2K3 w - - 0 1';

function boardSurface() {
  const element = screen.getByRole('group', { name: /交互棋盘/ });
  vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: 800,
    bottom: 800,
    width: 800,
    height: 800,
    toJSON: () => ({}),
  });
  element.setPointerCapture = vi.fn();
  return element;
}

function draw(
  element: HTMLElement,
  from: [number, number],
  to = from,
  shiftKey = false,
) {
  fireEvent.pointerDown(element, {
    button: 2,
    buttons: 2,
    pointerId: 1,
    clientX: from[0],
    clientY: from[1],
    shiftKey,
  });
  fireEvent.pointerMove(element, {
    buttons: 2,
    pointerId: 1,
    clientX: to[0],
    clientY: to[1],
  });
  fireEvent.pointerUp(element, {
    button: 2,
    pointerId: 1,
    clientX: to[0],
    clientY: to[1],
  });
}

beforeEach(() => {
  vi.stubGlobal(
    'PointerEvent',
    class extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 1;
      }
    },
  );
});

describe('WorkbenchBoard', () => {
  it('selects on press once, drags without scaling, and skips only the completed drag slide', () => {
    const onSquareClick = vi.fn();
    const onPieceDragBegin = vi.fn();
    const onPieceDragEnd = vi.fn();
    const onPieceDrop = vi.fn(() => true);
    const props = {
      onSquareClick,
      onPieceDragBegin,
      onPieceDragEnd,
      onPieceDrop,
    };
    const { container, rerender } = render(
      <WorkbenchBoard position={fen} {...props} />,
    );
    const surface = boardSurface();
    expect(screen.getByTestId('animation-duration').textContent).toBe('120');
    fireEvent.pointerDown(surface, {
      button: 0,
      pointerId: 2,
      clientX: 150,
      clientY: 750,
    });
    expect(onSquareClick).toHaveBeenCalledExactlyOnceWith('b1', 'wN');
    expect(onPieceDragBegin).not.toHaveBeenCalled();
    fireEvent.pointerMove(surface, {
      pointerId: 2,
      clientX: 151,
      clientY: 750,
    });
    expect(container.querySelector('.workbench-piece-preview')).toBeNull();
    fireEvent.pointerMove(surface, {
      pointerId: 2,
      clientX: 250,
      clientY: 550,
    });
    expect(onPieceDragBegin).toHaveBeenCalledExactlyOnceWith('wN', 'b1');
    const preview = container.querySelector(
      '.workbench-piece-preview',
    ) as HTMLElement;
    expect(preview.style.transform).toBe('translate(200px, 500px)');
    expect(preview.style.width).toBe('100px');
    expect(preview.style.transition).toBe('none');
    fireEvent.pointerUp(surface, { pointerId: 2, clientX: 250, clientY: 550 });
    fireEvent.click(surface);
    expect(onSquareClick).toHaveBeenCalledTimes(1);
    expect(onPieceDrop).toHaveBeenCalledExactlyOnceWith('b1', 'c3', 'wN');
    expect(onPieceDragEnd).toHaveBeenCalledTimes(1);
    expect(container.querySelector('.workbench-piece-preview')).toBeNull();
    expect(container.querySelector('.workbench-piece-origin')).toBeNull();
    rerender(
      <WorkbenchBoard
        position="r3k3/8/8/8/8/2N5/1P6/4K3 b - - 1 1"
        {...props}
      />,
    );
    expect(screen.getByTestId('animation-duration').textContent).toBe('0');
    rerender(<WorkbenchBoard position={fen} {...props} />);
    expect(screen.getByTestId('animation-duration').textContent).toBe('120');
  });

  it('cancels an outside or interrupted drag without submitting a move', () => {
    const onPieceDrop = vi.fn();
    const { container } = render(
      <WorkbenchBoard position={fen} onPieceDrop={onPieceDrop} />,
    );
    const surface = boardSurface();
    for (const end of ['pointerUp', 'pointerCancel'] as const) {
      fireEvent.pointerDown(surface, {
        button: 0,
        pointerId: 3,
        clientX: 150,
        clientY: 750,
      });
      fireEvent.pointerMove(surface, {
        pointerId: 3,
        clientX: 250,
        clientY: 550,
      });
      fireEvent[end](surface, { pointerId: 3, clientX: -50, clientY: 550 });
      expect(onPieceDrop).not.toHaveBeenCalled();
      expect(container.querySelector('.workbench-piece-preview')).toBeNull();
      expect(container.querySelector('.workbench-piece-origin')).toBeNull();
    }
  });

  it('draws and toggles circles, changes color and clears on left click', () => {
    const { container } = render(<WorkbenchBoard position={fen} />);
    const surface = boardSurface();
    draw(surface, [450, 450]);
    expect(container.querySelector('circle[data-from="e4"]')).toBeTruthy();
    draw(surface, [450, 450], [450, 450], true);
    expect(container.querySelectorAll('circle')).toHaveLength(1);
    expect(container.querySelector('circle')?.getAttribute('data-brush')).toBe(
      'red',
    );
    draw(surface, [450, 450], [450, 450], true);
    expect(container.querySelectorAll('circle')).toHaveLength(0);
    draw(surface, [450, 450]);
    fireEvent.pointerDown(surface, { button: 0, pointerId: 1 });
    expect(container.querySelectorAll('circle')).toHaveLength(0);
  });

  it('keeps manual arrows through engine updates, clears on FEN change, and cancels outside release', () => {
    const { container, rerender } = render(
      <WorkbenchBoard position={fen} customArrows={[]} />,
    );
    const surface = boardSurface();
    draw(surface, [650, 750], [550, 550]);
    expect(
      container.querySelector('path[data-from="g1"][data-to="f3"]'),
    ).toBeTruthy();
    rerender(<WorkbenchBoard position={fen} customArrows={[['b1', 'c3']]} />);
    expect(
      container.querySelector('path[data-source="engine"][data-to="c3"]'),
    ).toBeTruthy();
    expect(
      container.querySelectorAll('path[data-source="manual"]'),
    ).toHaveLength(1);
    draw(surface, [450, 450], [900, 450]);
    expect(
      container.querySelectorAll('path[data-source="manual"]'),
    ).toHaveLength(1);
    rerender(<WorkbenchBoard position="4k3/8/8/8/8/8/8/4K3 w - - 0 1" />);
    expect(container.querySelectorAll('[data-shape]')).toHaveLength(0);
  });

  it('renders manual and translucent engine arrows as single filled outlines without marker seams', () => {
    const { container } = render(
      <WorkbenchBoard
        position={fen}
        customArrows={[['a8', 'a4', 'rgba(31, 90, 165, 0.4)']]}
      />,
    );
    draw(boardSurface(), [650, 750], [550, 550]);
    const arrows = [...container.querySelectorAll('[data-shape="arrow"]')];
    expect(arrows).toHaveLength(2);
    for (const arrow of arrows) {
      expect(arrow.tagName.toLowerCase()).toBe('path');
      expect(arrow.getAttribute('d')).toMatch(/Z$/);
      expect(arrow.getAttribute('stroke')).toBe('none');
      expect(arrow.hasAttribute('marker-end')).toBe(false);
    }
    expect(arrows[0].getAttribute('fill')).toBe('rgba(31, 90, 165, 0.4)');
    expect(arrows[1].getAttribute('fill')).toBe('#15781b');
    expect(container.querySelectorAll('marker, line')).toHaveLength(0);
    expect(screen.getByTestId('engine-arrows').textContent).not.toContain('a8');
  });

  it('places each material difference and the positive score on the correct side when flipped', () => {
    const { container, rerender } = render(<WorkbenchBoard position={fen} />);
    const rows = () => [...container.querySelectorAll('.board-material')];
    expect(rows().map((row) => row.getAttribute('data-color'))).toEqual([
      'black',
      'white',
    ]);
    expect(rows()[0].textContent).toContain('+1');
    expect(rows()[1].getAttribute('aria-label')).toContain('1马、1兵');
    rerender(<WorkbenchBoard position={fen} boardOrientation="black" />);
    expect(rows().map((row) => row.getAttribute('data-color'))).toEqual([
      'white',
      'black',
    ]);
    expect(rows()[1].textContent).toContain('+1');
  });
});
