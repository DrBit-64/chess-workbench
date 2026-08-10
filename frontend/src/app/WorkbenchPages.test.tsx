import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SWRConfig } from 'swr';
import { describe, expect, it, vi } from 'vitest';

import { CourseCatalog } from './CourseCatalog';
import { Dashboard } from './Dashboard';
import { SourcesPage } from './SourcesPage';

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

function renderPage(node: React.ReactNode) {
  return render(
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      <MemoryRouter>{node}</MemoryRouter>
    </SWRConfig>,
  );
}

const course = {
  id: 'course-1',
  title: '西西里防御',
  description: '从开放西西里开始',
  mode: 'traditional',
  status: 'draft',
  tags: ['黑方'],
  version: 1,
  archived_at: null,
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
};

const source = {
  id: 'source-1',
  kind: 'book',
  title: 'My System',
  author: 'Nimzowitsch',
  publication_date: null,
  external_url: 'https://example.test/book',
  description: null,
  metadata: {},
  version: 1,
  archived_at: null,
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
};

describe('Stage 4A workbench pages', () => {
  it('renders real dashboard statistics and recent-course navigation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/dashboard/summary') {
          return json({
            course_count: 2,
            module_count: 3,
            source_count: 4,
            knowledge_note_count: 5,
            recent_courses: [course],
          });
        }
        return json({
          status: 'ok',
          service: 'chess-workbench-api',
          version: '0.1.0',
          database: 'ok',
        });
      }),
    );

    renderPage(<Dashboard />);

    expect(await screen.findByText('西西里防御')).toBeTruthy();
    expect(screen.getByText('5')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: /西西里防御/ }).getAttribute('href'),
    ).toBe('/learn/course-1');
  });

  it('shows dashboard API errors without replacing the shell', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        String(input) === '/api/dashboard/summary'
          ? json({}, 503)
          : json({}, 503),
      ),
    );

    renderPage(<Dashboard />);

    expect(await screen.findByText('无法读取工作台统计')).toBeTruthy();
    expect(
      screen.getByRole('heading', { name: '你的棋局知识工作台' }),
    ).toBeTruthy();
  });

  it('queries, filters, and creates courses through the API', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') return json(course, 201);
      return json([course]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<CourseCatalog />);

    expect(await screen.findByText('西西里防御')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('搜索课程'), {
      target: { value: '龙式' },
    });
    fireEvent.keyDown(screen.getByLabelText('搜索课程'), {
      key: 'Enter',
      code: 'Enter',
    });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('q=%E9%BE%99%E5%BC%8F'),
        expect.anything(),
      ),
    );

    fireEvent.click(screen.getByRole('button', { name: '新建课程' }));
    fireEvent.change(await screen.findByLabelText('课程名称'), {
      target: { value: '法兰西防御' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/courses',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ title: '法兰西防御', mode: 'traditional' }),
        }),
      ),
    );
  });

  it('renders an empty course result explicitly', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json([])),
    );
    renderPage(<CourseCatalog />);
    expect(await screen.findByText('没有匹配的课程')).toBeTruthy();
  });

  it('queries and creates manual sources', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') return json(source, 201);
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('My System')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: '打开原始链接' }).getAttribute('href'),
    ).toBe('https://example.test/book');
    fireEvent.change(screen.getByLabelText('搜索资料'), {
      target: { value: '体系' },
    });
    fireEvent.keyDown(screen.getByLabelText('搜索资料'), {
      key: 'Enter',
      code: 'Enter',
    });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('q=%E4%BD%93%E7%B3%BB'),
        expect.anything(),
      ),
    );

    fireEvent.click(screen.getByRole('button', { name: '添加手工来源' }));
    fireEvent.change(await screen.findByLabelText('标题'), {
      target: { value: '我的课堂笔记' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^添\s*加$/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/citable-sources',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ kind: 'manual', title: '我的课堂笔记' }),
        }),
      ),
    );
  });

  it('shows an explicit empty source state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json([])),
    );
    renderPage(<SourcesPage />);
    expect(await screen.findByText('还没有资料')).toBeTruthy();
  });
});
