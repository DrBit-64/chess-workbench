import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';
import { describe, expect, it, vi } from 'vitest';

import type { CourseModule } from '../logic/api/types';
import { LichessStudyExport } from './LichessStudyExport';

const chapter: CourseModule = {
  id: 'chapter',
  course_id: 'course',
  parent_id: null,
  title: '后兵开局',
  description: '',
  sort_order: 0,
  version: 1,
  archived_at: null,
  created_at: '2026-10-02T00:00:00Z',
  updated_at: '2026-10-02T00:00:00Z',
  start_occurrence_id: null,
};
const subsection: CourseModule = {
  ...chapter,
  id: 'subsection',
  parent_id: 'chapter',
  title: '例局一',
};
const otherChapter: CourseModule = {
  ...chapter,
  id: 'other-chapter',
  title: '残局专题',
  sort_order: 1,
};

function preview(scope: string | string[], configured = true) {
  const ids = typeof scope === 'string' ? [scope] : scope;
  return {
    name: '课程 · 后兵开局',
    token_configured: configured,
    chapters: ids.includes('chapter')
      ? [
          {
            module_id: 'chapter',
            name: '后兵开局',
            move_count: 0,
          },
          { module_id: 'subsection', name: '例局一', move_count: 30 },
          { module_id: 'second', name: '例局二', move_count: 48 },
        ]
      : [
          {
            module_id: 'subsection',
            name: '例局一',
            move_count: 30,
          },
        ],
    skipped_modules: [],
    warnings: [],
    blockers: [],
    max_chapters: 64,
  };
}

function mount(unsavedChanges = false) {
  render(
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      <LichessStudyExport
        courseId="course"
        moduleId="subsection"
        modules={[chapter, subsection, otherChapter]}
        orientation="black"
        unsavedChanges={unsavedChanges}
      />
    </SWRConfig>,
  );
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

describe('Lichess study publication', () => {
  it('previews multiple chapters with their children then sends the same selection once', async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === 'POST')
          return json({
            status: 'complete',
            study_url: 'https://lichess.org/study/Study123',
            imported_chapters: 4,
            expected_chapters: 4,
            message: '已创建研讨，导入 4 个章节',
          });
        const scope = new URL(
          String(input),
          'http://localhost',
        ).searchParams.getAll('module_ids');
        const selected = preview(scope);
        if (scope.includes(otherChapter.id))
          selected.chapters.push({
            module_id: otherChapter.id,
            name: otherChapter.title,
            move_count: 10,
          });
        return json(selected);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    mount();
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole('button', { name: '所选章节发送到 Lichess' }),
    );
    await screen.findByText('将创建 1 个研讨章节');
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '发送范围' }));
    fireEvent.click(
      await screen.findByText('整个章节：后兵开局（含所有小节）'),
    );
    await screen.findByText('将创建 3 个研讨章节');
    expect(screen.getByText('后兵开局 · 空章节（无棋步）')).toBeTruthy();
    expect(screen.getByText('例局一 · 30 个半回合')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('研讨名称'), {
      target: { value: '我的后兵课程' },
    });
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '发送范围' }));
    fireEvent.click(
      await screen.findByText('整个章节：残局专题（含所有小节）'),
    );
    await screen.findByText('将创建 4 个研讨章节');
    expect((screen.getByLabelText('研讨名称') as HTMLInputElement).value).toBe(
      '我的后兵课程',
    );
    fireEvent.click(screen.getByRole('button', { name: '创建并发送' }));
    const link = await screen.findByRole('link', { name: '打开 Lichess 研讨' });
    expect(link.getAttribute('href')).toBe(
      'https://lichess.org/study/Study123',
    );
    const posts = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === 'POST',
    );
    expect(posts).toHaveLength(1);
    expect(posts[0]?.[0]).toBe('/api/courses/course/lichess-studies');
    expect(JSON.parse(String(posts[0]?.[1]?.body))).toEqual({
      module_ids: ['subsection', 'chapter', 'other-chapter'],
      name: '我的后兵课程',
      orientation: 'black',
    });
    expect(
      screen
        .getByRole('button', { name: '已结束本次发送' })
        .hasAttribute('disabled'),
    ).toBe(true);
  });

  it('clearing the multi-selection disables publication without previewing the whole course', async () => {
    const fetchMock = vi.fn(async () => json(preview('subsection')));
    vi.stubGlobal('fetch', fetchMock);
    mount();
    fireEvent.click(
      screen.getByRole('button', { name: '所选章节发送到 Lichess' }),
    );
    await screen.findByText('将创建 1 个研讨章节');
    const calls = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: '清空选择' }));
    await screen.findByText('请至少选择一个章节或小节');
    expect(
      screen
        .getByRole('button', { name: '创建并发送' })
        .hasAttribute('disabled'),
    ).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(calls);
  });

  it('explains one-time token setup without asking for a token in the browser', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(preview('subsection', false))),
    );
    mount();
    fireEvent.click(
      screen.getByRole('button', { name: '所选章节发送到 Lichess' }),
    );
    await screen.findByText('首次使用需要配置 Lichess 令牌');
    expect(
      screen
        .getByRole('link', { name: 'Lichess 令牌页面' })
        .getAttribute('href'),
    ).toBe('https://lichess.org/account/oauth/token');
    expect(
      screen
        .getByRole('button', { name: '创建并发送' })
        .hasAttribute('disabled'),
    ).toBe(true);
    expect(screen.queryByLabelText(/API.*密钥|令牌值/)).toBeNull();
  });

  it('retains a partial result and its link, without offering automatic resubmission', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) =>
        json(
          init?.method === 'POST'
            ? {
                status: 'partial',
                study_url: 'https://lichess.org/study/Study123',
                imported_chapters: 0,
                expected_chapters: 1,
                message: '只确认导入 0/1 个章节，请检查研讨',
              }
            : preview('subsection'),
        ),
    );
    vi.stubGlobal('fetch', fetchMock);
    mount();
    fireEvent.click(
      screen.getByRole('button', { name: '所选章节发送到 Lichess' }),
    );
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: '创建并发送' })
          .hasAttribute('disabled'),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole('button', { name: '创建并发送' }));
    await screen.findByText('只确认导入 0/1 个章节，请检查研讨');
    expect(
      screen.getByRole('link', { name: '打开 Lichess 研讨' }),
    ).toBeTruthy();
    expect(
      screen
        .getByRole('button', { name: '已结束本次发送' })
        .hasAttribute('disabled'),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST'),
    ).toHaveLength(1);
  });

  it('does not publish unsaved edits', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(preview('subsection'))),
    );
    mount(true);
    fireEvent.click(
      screen.getByRole('button', { name: '所选章节发送到 Lichess' }),
    );
    await screen.findByText('将创建 1 个研讨章节');
    expect(
      screen.getByText('请先保存当前说明的修改，再发送到 Lichess'),
    ).toBeTruthy();
    expect(
      screen
        .getByRole('button', { name: '创建并发送' })
        .hasAttribute('disabled'),
    ).toBe(true);
  });
});
