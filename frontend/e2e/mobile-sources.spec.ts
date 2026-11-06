import { expect, test, type Locator, type Page } from '@playwright/test';

const title = 'Chess Structures: A Grandmaster Guide to Strategic Pawn Endings';
const filename =
  'ChessStructures_AGrandmasterGuide_AnnotatedGames_CompleteRevisedEdition2025.pdf';
const sourceTitle =
  'AnnotatedEndgameStudiesFromTheRevisedInternationalMastersCollection';
const asset = { id: 'book', title, filename, page_count: 240 };
const run = {
  id: 'first-run',
  pdf_asset_id: asset.id,
  first_page: 132,
  last_page: 149,
  created_at: '2026-09-01T12:00:00Z',
  pipeline_version: 'pdf-extraction:v8',
  job: { status: 'succeeded' },
  has_conflicts: true,
  candidate: {
    item_count: 12,
    move_node_count: 73,
    warning_count: 3,
    error_count: 1,
  },
};

async function openLibrary(page: Page) {
  const data: Record<string, unknown> = {
    '/api/pdf-assets': { items: [asset] },
    '/api/pdf-extractions': { items: [run] },
    '/api/pdf-extraction-documents': { items: [] },
    '/api/sources': [
      {
        id: 'notes',
        kind: 'web',
        title: sourceTitle,
        external_url: 'https://example.org/studies',
      },
    ],
  };
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) => {
      const { pathname } = new URL(route.request().url());
      if (
        route.request().method() === 'POST' &&
        pathname === '/api/pdf-extractions'
      ) {
        return route.fulfill({ json: { extraction: run } });
      }
      if (route.request().method() === 'GET' && pathname in data) {
        return route.fulfill({ json: data[pathname] });
      }
      return route.abort();
    },
  );
  await page.goto('/sources');
}

// Checking body width alone misses a title ellipsized inside a clipped card.
async function expectReadableText(locator: Locator) {
  await expect(locator).toBeVisible();
  const fits = () =>
    locator.evaluate((element) => {
      let left = 0;
      let right = document.documentElement.clientWidth;
      for (
        let parent: Element | null = element;
        parent;
        parent = parent.parentElement
      ) {
        if (getComputedStyle(parent).overflowX === 'visible') continue;
        const box = parent.getBoundingClientRect();
        left = Math.max(left, box.left);
        right = Math.min(right, box.right);
      }
      const range = document.createRange();
      range.selectNodeContents(element);
      return Array.from(range.getClientRects()).every(
        (rect) => rect.left >= left - 1 && rect.right <= right + 1,
      );
    });
  await expect
    .poll(fits, {
      message: 'text fits the viewport and its clipping ancestors',
    })
    .toBe(true);
}

test.describe('phone sources', () => {
  test.use({
    viewport: { width: 336, height: 741 },
    isMobile: true,
    hasTouch: true,
  });

  test('book metadata, source cards and extraction actions fit before and after rotation', async ({
    page,
  }) => {
    await openLibrary(page);
    const library = page.getByRole('region', { name: 'PDF 棋书' });
    await expectReadableText(library.getByText(title, { exact: true }));
    await expectReadableText(library.getByText(filename, { exact: false }));
    await expectReadableText(page.getByText(sourceTitle, { exact: true }));
    await expect(
      page.getByRole('link', { name: '打开原始链接' }),
    ).toHaveAttribute('href', 'https://example.org/studies');
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(336);

    await library.getByRole('button', { name: '管理提取结果' }).tap();
    const drawer = page.getByRole('dialog');
    await expectReadableText(drawer.getByText(filename, { exact: true }));
    const record = drawer.getByRole('listitem').filter({ hasText: '独立提取' });
    await expectReadableText(record.getByText('独立提取 · 第 132–149 页'));
    await record.getByRole('button', { name: '操作' }).tap();
    const review = page.getByRole('link', { name: '打开审核页面' });
    await expect(review).toBeInViewport({ ratio: 1 });
    await expect(review).toHaveAttribute(
      'href',
      '/sources/pdf-extractions/first-run/review',
    );
    await expect(
      page.getByRole('link', { name: '查看原文与页图' }),
    ).toHaveAttribute('href', '/sources/pdf-extractions/first-run/source');
    await record.getByRole('button', { name: '操作' }).tap();

    await page.setViewportSize({ width: 741, height: 228 });
    await drawer.getByRole('spinbutton', { name: '起始物理页' }).fill('4');
    await drawer.getByRole('spinbutton', { name: '结束物理页' }).fill('8');
    const sent = page.waitForRequest(
      (request) =>
        request.method() === 'POST' &&
        new URL(request.url()).pathname === '/api/pdf-extractions',
    );
    await drawer.getByRole('button', { name: '创建识别任务' }).tap();
    expect((await sent).postDataJSON()).toEqual({
      pdf_asset_id: asset.id,
      first_page: 4,
      last_page: 8,
      pipeline: 'source_first',
    });
  });

  test('upload and manual forms remain usable at 304px', async ({ page }) => {
    await page.setViewportSize({ width: 304, height: 741 });
    await openLibrary(page);
    await page.getByRole('button', { name: '上传 PDF 棋书' }).tap();
    const upload = page.getByRole('dialog', { name: '上传 PDF 棋书' });
    const file = upload.getByLabel('PDF 文件');
    await file.setInputFiles({
      name: filename,
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4'),
    });
    await expect(file).toBeInViewport({ ratio: 1 });
    await expect(
      upload.getByRole('button', { name: /上\s*传/ }),
    ).toBeInViewport({
      ratio: 1,
    });
    await upload.getByRole('button', { name: /cancel|取\s*消/i }).tap();
    await page.getByRole('button', { name: '添加其他资料' }).tap();
    const manual = page.getByRole('dialog', { name: '添加其他资料' });
    await manual.getByLabel('标题').fill('我的棋局笔记');
    await expect(
      manual.getByRole('button', { name: /添\s*加/ }),
    ).toBeInViewport({ ratio: 1 });
  });
});

test('desktop sources still exposes the book and review action', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await openLibrary(page);
  await page.getByRole('button', { name: '管理提取结果' }).click();
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByText(filename, { exact: true })).toBeVisible();
  await drawer.getByRole('button', { name: '操作' }).click();
  await expect(
    page.getByRole('link', { name: '打开审核页面' }),
  ).toHaveAttribute('href', '/sources/pdf-extractions/first-run/review');
});
