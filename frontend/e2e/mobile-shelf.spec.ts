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
