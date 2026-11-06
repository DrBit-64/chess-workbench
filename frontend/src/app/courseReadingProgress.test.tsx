import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { useReadingScroll } from './courseReadingProgress';

function Reader({ ready }: { ready: boolean }) {
  const scroll = useReadingScroll('slow-source', 'chapter', null, ready);
  return <article ref={scroll} />;
}

it('prefers a new scroll over the previous bookmark while source metadata loads', () => {
  const key = 'chess-workbench.reader.v1.slow-source.text.chapter';
  localStorage.setItem(key, JSON.stringify({ top: 300 }));
  vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(512);
  const { rerender, unmount } = render(<Reader ready={false} />);
  const panel = screen.getByRole('article');
  fireEvent.wheel(panel, { deltaY: 1100 });
  panel.scrollTop = 1100;
  fireEvent.scroll(panel);
  rerender(<Reader ready />);
  expect(panel.scrollTop).toBe(1100);
  unmount();

  const reopened = render(<Reader ready={false} />);
  reopened.rerender(<Reader ready />);
  expect(screen.getByRole('article').scrollTop).toBe(1100);
  reopened.unmount();
  localStorage.removeItem(key);
});
