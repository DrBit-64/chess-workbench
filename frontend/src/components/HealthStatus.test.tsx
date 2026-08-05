import { render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';
import { describe, expect, it, vi } from 'vitest';

import { HealthStatus } from './HealthStatus';

function renderHealthStatus() {
  return render(
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      <HealthStatus />
    </SWRConfig>,
  );
}

describe('HealthStatus', () => {
  it('shows a loading state while the request is pending', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => undefined)),
    );

    renderHealthStatus();

    expect(screen.getByText('正在检查系统状态')).toBeTruthy();
  });

  it('renders API and database details after a successful health check', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: 'ok',
            service: 'chess-workbench-api',
            version: '0.1.0',
            database: 'ok',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );

    renderHealthStatus();

    expect(await screen.findByText('服务正常')).toBeTruthy();
    expect(screen.getByText('chess-workbench-api')).toBeTruthy();
    expect(screen.getByText('SQLite 已连接')).toBeTruthy();
  });

  it('renders a useful error when the API returns a failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('{}', { status: 503 })),
    );

    renderHealthStatus();

    expect(await screen.findByText('API 暂不可用')).toBeTruthy();
    expect(screen.getByText(/Sanic 服务/)).toBeTruthy();
  });
});
