import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SWRConfig } from 'swr';
import { describe, expect, it, vi } from 'vitest';

import { App } from './App';

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
        name: /把资料、局面与练习连成一条学习闭环/,
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
});
