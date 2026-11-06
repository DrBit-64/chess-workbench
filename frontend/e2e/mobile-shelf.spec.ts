import { expect, test } from '@playwright/test';
import { Chess } from 'chess.js';

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

test('a mainline page link can be tapped without selecting the next move', async ({
  page,
}) => {
  await page.setViewportSize({ width: 741, height: 320 });
  const game = new Chess();
  const chapter = { id: 'line', parent_id: null, title: '例局' };
  const root = {
    id: 'start',
    parent_id: null,
    module_id: chapter.id,
    full_fen: game.fen(),
  };
  const moves = ['e4', 'e5', 'Nf3'];
  const occurrences = [
    root,
    ...moves.map((san, index) => {
      const move = game.move(san);
      return {
        id: san,
        parent_id: moves[index - 1] ?? root.id,
        module_id: chapter.id,
        full_fen: game.fen(),
        inbound_san: san,
        inbound_uci: move.from + move.to,
        nag: null,
        sort_order: 0,
        context: { source_span_ids: [String(12 + index)] },
      };
    }),
  ];
  const sourceFile = { source_file_id: 'f', source_version_id: 'v' };
  const responses: Record<string, unknown> = {
    '/api/courses/book': { id: 'book', title: '棋书', mode: 'traditional' },
    '/api/courses/book/modules': [chapter],
    '/api/courses/book/editor/line': {
      module: chapter,
      content_blocks: [],
      notes: [],
      occurrences,
    },
    '/api/engine/capabilities': { available: false, syzygy_available: false },
    '/api/citable-sources': [12, 13].map((number) => ({
      source: { title: '例局原书' },
      source_span: {
        id: String(number),
        ...sourceFile,
        locator: { kind: 'page', page_number: number },
      },
    })),
    '/api/pdf-assets': {
      items: [{ id: 'scan', ...sourceFile, page_count: 20 }],
    },
  };
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.startsWith('/api/pdf-assets/scan/pages/'))
        return route.fulfill({
          contentType: 'image/svg+xml',
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="160"/>',
        });
      return route.fulfill({ json: responses[path] });
    },
  );

  await page.goto('/learn/book');
  for (const [label, number] of [
    ['e4 e2e4', 12],
    ['e5 e7e5', 13],
  ] as const) {
    const move = page.getByRole('button', { name: label, exact: true });
    await move.tap();
    const citation = page.getByRole('button', {
      name: `原书第 ${number} 页`,
      exact: true,
    });
    await citation.scrollIntoViewIfNeeded();
    // The previous layout put the visible link over the next move's hit area.
    const { height, receivesTouch } = await citation.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + 8, box.bottom - 4);
      return { height: box.height, receivesTouch: element.contains(hit) };
    });
    expect(receivesTouch).toBe(true);
    expect(height).toBeGreaterThanOrEqual(44);
    await citation.tap({ position: { x: 8, y: height - 4 } });
    await expect(
      page.getByRole('img', { name: `例局原书 第 ${number} 页` }),
    ).toBeVisible();
    await page.getByRole('button', { name: '讲解', exact: true }).tap();
    await expect(move).toHaveAttribute('aria-current', 'step');
  }
  const next = page.getByRole('button', { name: 'Nf3 g1f3', exact: true });
  await next.tap();
  await expect(next).toHaveAttribute('aria-current', 'step');
});
