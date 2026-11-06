import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { CourseWorkbenchLayout } from './CourseWorkbenchLayout';

const storageKey = 'chess-workbench.course-pane-widths';

function renderLayout() {
  return render(
    <CourseWorkbenchLayout>
      <aside>目录</aside>
      <section>棋盘</section>
      <article>内容</article>
    </CourseWorkbenchLayout>,
  );
}

beforeEach(() => {
  localStorage.clear();
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

it('resizes only adjacent panes, respects minimums and restores the saved layout', () => {
  const { container, unmount } = renderLayout();
  const grid = container.firstElementChild as HTMLElement;
  const measured = [380, 500, 520];
  [0, 2, 4].forEach((index, pane) => {
    vi.spyOn(grid.children[index], 'getBoundingClientRect').mockReturnValue({
      width: measured[pane],
    } as DOMRect);
  });
  const separator = screen.getByRole('separator', {
    name: '调整目录与棋盘宽度',
  });
  separator.setPointerCapture = vi.fn();
  fireEvent.pointerDown(separator, { button: 0, pointerId: 1, clientX: 380 });
  fireEvent.pointerMove(separator, { pointerId: 1, clientX: 280 });
  expect(grid.style.getPropertyValue('--course-left-width')).toBe('280fr');
  expect(grid.style.getPropertyValue('--course-board-width')).toBe('600fr');
  expect(grid.style.getPropertyValue('--course-reading-width')).toBe('520fr');
  expect(localStorage.getItem(storageKey)).toBeNull();
  fireEvent.pointerMove(separator, { pointerId: 1, clientX: -500 });
  expect(grid.style.getPropertyValue('--course-left-width')).toBe('220fr');
  fireEvent.pointerUp(separator, { pointerId: 1 });
  expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual([
    220, 660, 520,
  ]);
  unmount();

  const restored = renderLayout().container.firstElementChild as HTMLElement;
  expect(restored.style.getPropertyValue('--course-board-width')).toBe('660fr');
  fireEvent.doubleClick(screen.getAllByRole('separator')[0]);
  expect(restored.style.getPropertyValue('--course-left-width')).toBe('380fr');
  expect(restored.style.getPropertyValue('--course-board-width')).toBe('500fr');
  expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual(measured);
});

it('supports keyboard adjustment and cancels an interrupted drag without saving it', () => {
  const { container } = renderLayout();
  const grid = container.firstElementChild as HTMLElement;
  [380, 500, 520].forEach((width, pane) => {
    vi.spyOn(grid.children[pane * 2], 'getBoundingClientRect').mockReturnValue({
      width,
    } as DOMRect);
  });
  const separator = screen.getByRole('separator', {
    name: '调整棋盘与内容宽度',
  });
  fireEvent.keyDown(separator, { key: 'ArrowRight' });
  expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual([
    380, 516, 504,
  ]);
  separator.setPointerCapture = vi.fn();
  fireEvent.pointerDown(separator, { button: 0, pointerId: 2, clientX: 900 });
  fireEvent.pointerMove(separator, { pointerId: 2, clientX: 1200 });
  expect(grid.style.getPropertyValue('--course-reading-width')).toBe('320fr');
  fireEvent.pointerCancel(separator, { pointerId: 2 });
  expect(grid.style.getPropertyValue('--course-board-width')).toBe('516fr');
  expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual([
    380, 516, 504,
  ]);
  expect(grid.classList.contains('is-resizing')).toBe(false);
});
