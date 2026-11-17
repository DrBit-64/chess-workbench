import { expect, test } from '@playwright/test';
import { Chess } from 'chess.js';

test.use({
  viewport: { width: 741, height: 228 },
  isMobile: true,
  hasTouch: true,
});

test('the phone reader analyzes trial moves, records a variation and keeps a new chapter selected during a save', async ({
  page,
  request,
}, testInfo) => {
  const title = '手机课程走棋验收';
  const imported = await request.post('/api/pgn/imports', {
    data: {
      pgn: '[Event "主线练习"]\n[Result "*"]\n\n1. d4 d5 *\n\n[Event "另一章"]\n[Result "*"]\n\n1. c4 e5 *',
      destination: { kind: 'new_course', title },
    },
  });
  expect(imported.ok(), await imported.text()).toBeTruthy();
  const { import_receipt } = await imported.json();
  const courseId = import_receipt.course_id;
  const modules = await (
    await request.get(`/api/courses/${courseId}/modules`)
  ).json();
  const first = modules.find(
    (item: { title: string }) => item.title === '主线练习',
  );
  const editorUrl = `/api/courses/${courseId}/editor/${first.id}`;
  const initial = await (await request.get(editorUrl)).json();
  let writes = 0;
  page.on('request', (item) => {
    if (item.url().endsWith('/api/occurrences') && item.method() === 'POST')
      writes += 1;
  });
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(String(error)));
  await page.goto('/learn');
  await page.getByRole('link', { name: new RegExp(title) }).tap();
  const board = page.locator('.course-board-pane');
  const square = (name: string) => board.locator(`[data-square="${name}"]`);
  const score = page.locator('.course-reading-scroll');
  const record = page.getByRole('button', { name: '记录走棋', exact: true });
  await expect(record).toBeInViewport();
  await expect(record).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('checkbox', { name: '记录走棋' })).toHaveCount(0);
  const trial = new Chess();
  trial.move('e4');
  const analysis = page.waitForResponse(
    (item) =>
      item.url().endsWith('/api/engine/analyses') &&
      item.request().postDataJSON().fen === trial.fen(),
  );
  await square('e2').tap();
  await square('e4').tap();
  await expect(square('e4').locator('[data-piece="wP"]')).toBeVisible();
  expect((await analysis).ok()).toBeTruthy();
  await expect(
    board.getByRole('meter', { name: '引擎局面评分' }),
  ).toBeVisible();
  await expect(board.locator('[data-source="engine"]').first()).toBeVisible();
  await expect(page.getByRole('region', { name: '课程实时引擎' })).toHaveCount(
    0,
  );

  // Exercise a real touch drag as well as tap-to-move.
  const source = (await square('e7').boundingBox())!;
  const target = (await square('e5').boundingBox())!;
  const touch = await page.context().newCDPSession(page);
  const from = {
    x: source.x + source.width / 2,
    y: source.y + source.height / 2,
  };
  const to = {
    x: target.x + target.width / 2,
    y: target.y + target.height / 2,
  };
  await touch.send('Input.dispatchTouchEvent', {
    type: 'touchStart',
    touchPoints: [{ ...from, id: 1 }],
  });
  // Let the browser process the pointer capture and frames of a normal drag.
  for (let step = 1; step <= 8; step += 1) {
    await page.evaluate(
      () =>
        new Promise<void>((resolve) => requestAnimationFrame(() => resolve())),
    );
    await touch.send('Input.dispatchTouchEvent', {
      type: 'touchMove',
      touchPoints: [
        {
          x: from.x + ((to.x - from.x) * step) / 8,
          y: from.y + ((to.y - from.y) * step) / 8,
          id: 1,
        },
      ],
    });
  }
  await touch.send('Input.dispatchTouchEvent', {
    type: 'touchEnd',
    touchPoints: [],
  });
  await touch.detach();
  await expect(square('e5').locator('[data-piece="bP"]')).toBeVisible();
  expect(writes).toBe(0);
  const returned = page.getByRole('button', { name: '返回原谱局面' });
  await expect(returned).toBeInViewport();
  await returned.tap();
  await expect(square('e2').locator('[data-piece="wP"]')).toBeVisible();
  expect((await (await request.get(editorUrl)).json()).occurrences).toEqual(
    initial.occurrences,
  );

  await record.tap();
  await expect(record).toHaveAttribute('aria-pressed', 'true');
  const save = page.waitForResponse(
    (item) =>
      item.url().endsWith('/api/occurrences') &&
      item.request().method() === 'POST',
  );
  await square('e2').tap();
  await square('e4').tap();
  expect((await save).ok()).toBeTruthy();
  const savedMove = score.getByRole('button', { name: 'e4 e2e4', exact: true });
  await expect(savedMove).toHaveAttribute('aria-current', 'step');
  expect(writes).toBe(1);
  await page.screenshot({
    path: testInfo.outputPath('recorded-landscape.png'),
  });
  await page.reload();
  await expect(savedMove).toHaveAttribute('aria-current', 'step');
  await record.tap();
  const held = Promise.withResolvers<void>();
  await page.route(
    '**/api/occurrences',
    async (route) => {
      await held.promise;
      await route.continue();
    },
    { times: 1 },
  );
  try {
    await square('e7').tap();
    await square('e5').tap();
    await expect(record).toBeDisabled();
    await square('g1').tap();
    await square('f3').tap();
    expect(writes).toBe(2);
    await page.getByRole('button', { name: '更多阅读选项' }).tap();
    await page.getByRole('menuitem', { name: '章节目录' }).tap();
    await page.getByRole('button', { name: '另一章', exact: true }).tap();
    await page.getByRole('button', { name: '下一步', exact: true }).tap();
    const c4 = score.getByRole('button', { name: 'c4 c2c4', exact: true });
    await expect(c4).toHaveAttribute('aria-current', 'step');
    held.resolve();
    await expect(record).toBeEnabled();
    await expect(c4).toHaveAttribute('aria-current', 'step');
    await expect(square('c4').locator('[data-piece="wP"]')).toBeVisible();
    await page.setViewportSize({ width: 336, height: 741 });
    await expect(record).toBeInViewport();
    await expect(
      page.getByRole('button', { name: '下一步', exact: true }),
    ).toBeInViewport();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - innerWidth,
      ),
    ).toBeLessThanOrEqual(1);
    expect(
      (await (await request.get(editorUrl)).json()).occurrences,
    ).toHaveLength(initial.occurrences.length + 2);
    await record.tap();
    await square('c7').tap();
    await square('c5').tap();
    await expect(returned).toBeInViewport();
    expect(
      await page
        .locator('.course-score-controls')
        .evaluate((element) => element.clientHeight),
    ).toBeLessThan(60);
    await page.screenshot({ path: testInfo.outputPath('trial-portrait.png') });
    await returned.tap();
    await expect(square('c7').locator('[data-piece="bP"]')).toBeVisible();
    expect(pageErrors).toEqual([]);
  } finally {
    held.resolve();
  }
});
