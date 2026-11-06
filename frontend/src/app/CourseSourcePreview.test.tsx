import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { CourseSourcePreview } from './CourseSourcePreview';

it('restores the viewed part of each scan after turning a page or reopening at another width', () => {
  const renderPage = (page: number) => (
    <CourseSourcePreview
      preview={{
        assetId: 'test-book',
        page,
        title: 'Test book',
        contentUrl: `/scan/${page}`,
      }}
      moduleId="test-chapter"
      pageIndex={page - 1}
      pageCount={2}
      onPage={vi.fn()}
    />
  );
  const loadScan = (width: number) => {
    const area = screen.getByRole('region', { name: '原书页面滚动区' });
    const image = screen.getByRole('img');
    Object.defineProperties(area, {
      clientWidth: { configurable: true, value: width },
      scrollWidth: { configurable: true, value: width * 2 },
      scrollHeight: { configurable: true, value: width * 3 },
    });
    Object.defineProperties(image, {
      complete: { configurable: true, value: true },
      naturalWidth: { configurable: true, value: 1200 },
    });
    fireEvent.load(image);
    return area;
  };

  const first = render(renderPage(1));
  const area = loadScan(400);
  fireEvent.click(screen.getByRole('button', { name: '放大扫描页' }));
  area.scrollLeft = 200;
  area.scrollTop = 300;
  fireEvent.scroll(area);

  first.rerender(renderPage(2));
  expect(loadScan(400).scrollTop).toBe(0);
  expect(screen.getByRole('button', { name: '放大扫描页' })).toBeTruthy();
  first.unmount();
  render(renderPage(1));

  const reopened = loadScan(600);
  expect(screen.getByRole('img').style.width).toBe('200%');
  expect(reopened.scrollTop).toBe(450);
  expect(reopened.scrollLeft).toBe(300);
});
