import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SWRConfig } from 'swr';
import { describe, expect, it, vi } from 'vitest';

import { App } from './App';

vi.mock('./PdfReviewPage', () => ({
  PdfReviewPage: ({ runId }: { runId: string }) => (
    <div data-testid="pdf-review-page" data-run-id={runId}>
      审核页内容
    </div>
  ),
}));

function renderAt(path: string) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </SWRConfig>,
  );
}

describe('App routing', () => {
  it('renders the dashboard at the root route', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => undefined)),
    );

    renderAt('/');

    expect(
      screen.getByRole('heading', {
        name: /你的棋局知识工作台/,
      }),
    ).toBeTruthy();
  });

  it('renders a not-found page for unknown routes', () => {
    renderAt('/not-implemented');

    expect(screen.getByText('页面不存在')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: '返回首页' }).getAttribute('href'),
    ).toBe('/');
  });

  it('renders a not-found page for a review-shaped path missing the runId', () => {
    renderAt('/sources/pdf-extractions/review');

    expect(screen.getByText('页面不存在')).toBeTruthy();
  });

  it('renders the review route with the exact decoded runId once and no API request', async () => {
    const fetchMock = vi.fn(() => new Promise(() => undefined));
    vi.stubGlobal('fetch', fetchMock);

    renderAt('/sources/pdf-extractions/run%20abc/review');

    expect(
      await screen.findByRole('heading', { name: 'AI 棋书审核' }),
    ).toBeTruthy();
    expect(
      screen.getByRole('link', { name: '← 返回资料' }).getAttribute('href'),
    ).toBe('/sources');
    const review = screen.getAllByTestId('pdf-review-page');
    expect(review).toHaveLength(1);
    expect(review[0].getAttribute('data-run-id')).toBe('run abc');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
