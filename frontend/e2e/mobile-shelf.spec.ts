import { expect, test } from '@playwright/test';

test.use({
  viewport: { width: 336, height: 741 },
  isMobile: true,
  hasTouch: true,
});

test('a long book title and its settings fit on the portrait shelf', async ({
  page,
}) => {
  const title = 'Chess Structures: A Grandmaster Guide';
  await page.route('**/api/courses?**', (route) =>
    route.fulfill({
      json: [
        {
          id: 'structures',
          title,
          description:
            'Illustrative games with full-source teaching commentary.',
          mode: 'traditional',
          status: 'draft',
          tags: ['传统课程'],
        },
      ],
    }),
  );
  await page.goto('/learn');
  const book = page.getByRole('link', { name: title, exact: true });
  await expect(book).toBeVisible();
  const settings = page.getByRole('button', { name: title + ' 设置' });
  await expect(settings).toBeInViewport({ ratio: 1 });
  await expect(
    page.getByRole('link', { name: '学习', exact: true }),
  ).toBeInViewport({ ratio: 1 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(336);
  await settings.tap();
  await expect(page.getByText('重命名课程', { exact: true })).toBeVisible();
});

test('a prose chapter uses the entire landscape reading area', async ({
  page,
}) => {
  await page.setViewportSize({ width: 844, height: 390 });
  const chapter = { id: 'intro', parent_id: null, title: '前言' };
  const editor = {
    module: chapter,
    notes: [],
    content_blocks: [
      {
        id: 'text',
        kind: 'narrative',
        markdown: '阅读本书的方法',
        source_span_ids: [],
      },
    ],
    occurrences: [
      {
        id: 'root',
        module_id: chapter.id,
        parent_id: null,
        full_fen: 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
      },
    ],
  };
  const responses: Record<string, unknown> = {
    '/api/citable-sources': [],
    '/api/courses/book': { id: 'book', title: '棋书', mode: 'traditional' },
    '/api/courses/book/modules': [chapter],
    '/api/courses/book/editor/intro': editor,
  };
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) =>
      route.fulfill({
        json: responses[new URL(route.request().url()).pathname],
      }),
  );
  await page.goto('/learn/book');
  await expect(page.getByText('阅读本书的方法', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '更多阅读选项' }).click();
  await page.getByRole('menuitem', { name: '章节目录' }).click();
  await page.getByRole('button', { name: '讲解' }).click();
  const readingArea = page.locator('.course-reading-scroll');
  const width = () => readingArea.evaluate((element) => element.clientWidth);
  expect(await width()).toBe(844);
  await page.getByRole('button', { name: '全屏阅读' }).click();
  await expect(page.getByRole('button', { name: '退出全屏' })).toBeVisible();
  expect(await width()).toBe(844);
});
