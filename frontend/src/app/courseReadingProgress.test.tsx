import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { readReadingPlace, useReadingScroll } from './courseReadingProgress';

it('restores legacy scan choices only when the reader had opened the source', () => {
  const key = 'chess-workbench.reader.v1.legacy-book';
  const place = {
    moduleId: 'chapter',
    occurrenceId: 'e4',
    sourceSpanId: 'page-1',
    panel: 'score',
  };
  const search = new URLSearchParams();
  for (const leftPane of ['chapters', 'source']) {
    localStorage.setItem(key, JSON.stringify({ ...place, leftPane }));
    expect(readReadingPlace('legacy-book', search)?.sourceOccurrenceId).toBe(
      leftPane === 'source' ? 'e4' : null,
    );
  }
  localStorage.removeItem(key);
});

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
