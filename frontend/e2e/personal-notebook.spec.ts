import { randomUUID } from 'node:crypto';

import {
  expect,
  test as base,
  type Locator,
  type Page,
} from '@playwright/test';

const test = base.extend<{ phone: Page }>({
  phone: async ({ browser, baseURL }, runTest, testInfo) => {
    const handset = await browser
      .browserType()
      .launch(testInfo.project.use.launchOptions);
    try {
      const page = await handset.newPage({
        baseURL,
        viewport: { width: 336, height: 741 },
        isMobile: true,
        hasTouch: true,
      });
      await runTest(page);
    } finally {
      await handset.close();
    }
  },
});

function gamePgn(white: string, moves: string) {
  return [
    '[Event "Notebook acceptance"]',
    '[Site "?"]',
    '[Date "2026.11.07"]',
    `[White "${white}"]`,
    '[Black "Notebook opponent"]',
    '[Result "1/2-1/2"]',
    '',
    moves + ' 1/2-1/2',
  ].join('\n');
}

async function withinScreen(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      ),
    )
    .toBeLessThanOrEqual(1);
}

async function clickableTarget(control: Locator) {
  await control.scrollIntoViewIfNeeded();
  await expect(control).toBeInViewport({ ratio: 0.95 });
  expect(
    await control.evaluate((element) => {
      const { left, top, width, height } = element.getBoundingClientRect();
      return element.contains(
        document.elementFromPoint(left + width / 2, top + height / 2),
      );
    }),
  ).toBe(true);
}

test('saved games retain exact decision positions across touch capture, desktop search and source navigation', async ({
  page,
  phone,
  request,
}) => {
  // This journey spans two browsers and several independent page reloads.
  test.setTimeout(180_000);
  const suffix = randomUUID().slice(0, 8);
  const first = '转置甲-' + suffix;
  const second = '转置乙-' + suffix;
  const skipped = '跳过丙-' + suffix;
  const collection = [
    gamePgn(
      first,
      '1. Nf3 d5 2. g3 (2. d4 c6 {分析分支里的原注}) 2... Nf6 3. Bg2',
    ),
    gamePgn(second, '1. g3 d5 2. Nf3 Nf6 3. Bg2'),
    gamePgn(skipped, '1. e4 e5'),
  ].join('\n\n');

  await page.goto('/games');
  await page.getByRole('button', { name: '收录棋谱' }).click();
  const preview = page.getByRole('dialog');
  await preview.getByRole('textbox', { name: 'PGN 棋谱' }).fill(collection);
  await preview.getByRole('button', { name: '预览棋谱' }).click();
  await preview.getByRole('checkbox', { name: new RegExp(skipped) }).uncheck();
  const imported = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/notebook/imports') &&
      response.request().method() === 'POST',
  );
  await preview.getByRole('button', { name: /收录所选棋谱/ }).click();
  const result = await imported;
  expect(result.ok(), await result.text()).toBeTruthy();
  const { games } = (await result.json()) as {
    games: { id: string; index: number; created: boolean }[];
  };
  expect(games.map((game) => game.created)).toEqual([true, true]);
  const gameId = games.find((game) => game.index === 0)!.id;
  const secondId = games.find((game) => game.index === 1)!.id;
  const source = await request.get('/api/notebook/games/' + gameId);
  const { nodes } = (await source.json()) as {
    nodes: {
      id: string;
      parent_id: string | null;
      san: string | null;
      is_mainline: boolean;
    }[];
  };
  const decision = nodes.find(
    (node) => node.is_mainline && node.san === 'Nf6',
  )!;
  const variation = nodes.find(
    (node) => !node.is_mainline && node.san === 'c6',
  )!;
  const anchor = `/games/${gameId}?node=${decision.parent_id}`;

  await phone.goto(`/games/${gameId}?node=${decision.id}`);
  await withinScreen(phone);
  const showNotes = phone.getByRole('button', {
    name: '评语与收藏',
    exact: true,
  });
  await showNotes.tap();
  await phone.getByRole('button', { name: '写棋步评语' }).tap();
  const noteDialog = phone.getByRole('dialog');
  await noteDialog
    .getByRole('textbox', { name: '棋步评语' })
    .fill('我当时考虑立即出马');
  await noteDialog.getByRole('button', { name: /^保\s*存$/ }).tap();
  await phone.getByRole('button', { name: '棋步菜单' }).tap();
  await phone.getByText('收藏走这步之前', { exact: true }).tap();

  await expect(phone).toHaveURL((url) => url.pathname + url.search === anchor);
  await phone.getByRole('button', { name: '编辑局面收藏' }).tap();
  const edit = phone.getByRole('dialog', { name: '编辑收藏' });
  await edit
    .getByLabel('标题', { exact: true })
    .fill('换序与王的位置 ' + suffix);
  await edit.getByLabel('局面评语').fill('考虑王的位置，然后再决定换子。');
  await edit.getByLabel('添加标签').fill('换序');
  await edit.getByRole('button', { name: '添加', exact: true }).tap();
  await edit.getByLabel('添加标签').fill('关键决策');
  await edit.getByRole('button', { name: '保存', exact: true }).tap();
  await expect(edit).not.toBeVisible();
  await phone.getByRole('button', { name: '棋步菜单' }).tap();
  await phone.getByText('关联刚走的棋步', { exact: true }).tap();
  const related = phone.locator('.game-review-related');
  await expect(related.getByRole('button', { name: '2. g3' })).toBeVisible();
  await expect(related.getByRole('button', { name: '2... Nf6' })).toBeVisible();

  await phone.setViewportSize({ width: 741, height: 228 });
  await withinScreen(phone);
  const fullscreen = phone.getByRole('button', { name: '全屏阅读' });
  await clickableTarget(fullscreen);
  await fullscreen.tap();
  await expect
    .poll(() => phone.evaluate(() => Boolean(document.fullscreenElement)))
    .toBe(true);
  await withinScreen(phone);
  await phone.getByRole('button', { name: '退出全屏' }).tap();
  await phone.goto(`/games/${gameId}?node=${variation.id}`);
  await expect(phone.locator('[aria-current="step"]')).toContainText('c6');
  await phone.getByRole('button', { name: '收藏当前局面' }).tap();
  await expect(
    phone.getByRole('button', { name: '编辑局面收藏' }),
  ).toBeVisible();

  await page.goto('/games/positions');
  const branch = page
    .locator('.nb-position')
    .filter({ hasText: first })
    .filter({ hasText: 'c6' });
  await branch.getByRole('link', { name: '回到收藏处' }).click();
  await expect(page).toHaveURL(
    (url) => url.searchParams.get('node') === variation.id,
  );
  await expect(page.locator('[aria-current="step"]')).toHaveAccessibleName(
    /分析变例/,
  );
  await page.getByRole('button', { name: '返回列表' }).click();
  const search = page.getByLabel('搜索局面');
  await search.fill('立即出马');
  const card = page
    .locator('.nb-position')
    .filter({ hasText: '换序与王的位置 ' + suffix });
  await expect(card).toHaveCount(1);
  await expect(card).toContainText('棋步评语');
  await card.getByRole('link', { name: '练习局面' }).click();
  await page.getByRole('button', { name: '创建练习' }).click();
  await page.getByLabel('题目').fill('黑方怎样继续出子？');
  await page.getByRole('button', { name: '填入原谱续着' }).click();
  await expect(page.getByLabel('答案变化')).toHaveValue(/Nf6.*Bg2/);
  await page.getByRole('button', { name: '保存练习' }).click();
  await expect(
    page.getByRole('heading', { name: '黑方怎样继续出子？' }),
  ).toBeVisible();
  await page.locator('[data-square="c7"]').click();
  await page.locator('[data-square="c6"]').click();
  await expect(page.getByRole('status')).toContainText('没有列入');
  await page.locator('[data-square="g8"]').click();
  await page.locator('[data-square="f6"]').click();
  await expect(page.getByRole('status')).toContainText('已完成');
  await page.getByRole('button', { name: '删除练习' }).click();
  await page.getByRole('button', { name: '确认删除练习' }).click();
  await expect(page.getByRole('button', { name: '创建练习' })).toBeVisible();
  await page.getByRole('button', { name: /^返\s*回$/ }).click();
  await expect(search).toHaveValue('立即出马');
  await search.fill('然后再决定');
  await expect(card).toContainText('局面评语');
  await card.getByRole('button', { name: '换序', exact: true }).click();
  await card.getByRole('button', { name: '关键决策', exact: true }).click();
  await expect(card).toHaveCount(1);
  await withinScreen(page);
  await card.getByRole('link', { name: '回到收藏处' }).click();
  await expect(page).toHaveURL(
    (url) =>
      url.pathname === '/games/' + gameId &&
      url.searchParams.get('node') === decision.parent_id,
  );
  await page.getByRole('button', { name: '上一步' }).click();
  await expect(page).toHaveURL(
    (url) => url.searchParams.get('node') !== decision.parent_id,
  );
  await page.getByRole('button', { name: '返回列表' }).click();
  await expect(search).toHaveValue('然后再决定');
  await card.getByRole('button', { name: '查其他出现' }).click();
  const same = page.getByRole('dialog');
  await same.getByRole('link', { name: new RegExp(second) }).click();
  await expect(page).toHaveURL((url) => url.pathname === '/games/' + secondId);
  await expect(page.locator('[aria-current="step"]')).toHaveAccessibleName(
    /Nf3/,
  );

  await page.goto(anchor);
  await page.getByRole('button', { name: '取消收藏', exact: true }).click();
  await page.getByRole('button', { name: '收藏当前局面' }).click();
  await page.getByRole('button', { name: '编辑局面收藏' }).click();
  await expect(page.getByLabel('局面评语')).toHaveValue(
    '考虑王的位置，然后再决定换子。',
  );
  await page.getByRole('button', { name: '关闭弹窗' }).click();
  await page.goto('/games');
  const sourceRow = page.getByRole('listitem').filter({ hasText: first });
  await sourceRow.getByRole('button', { name: '归档' }).click();
  await expect(sourceRow).toHaveCount(0);
  await page.goto('/games/positions');
  await search.fill('立即出马');
  await expect(card).toContainText('棋步评语');
  await card.getByRole('link', { name: '回到收藏处' }).click();
  await expect(page.locator('[aria-current="step"]')).toContainText('g3');
  await expect(page.getByText(/已归档/)).toBeVisible();
  await page.goto('/games?archived=1');
  await sourceRow.getByRole('button', { name: '恢复' }).click();
  await expect(sourceRow).toHaveCount(0);
  await page.getByRole('button', { name: '已收录' }).click();
  await expect(sourceRow).toHaveCount(1);
  await page.goto('/games/positions');
  await search.fill('立即出马');
  await expect(card).toContainText('棋步评语');
  await card.getByText('管理收藏', { exact: true }).click();
  await card.getByRole('button', { name: '删除收藏', exact: true }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: '确认删除收藏' })
    .click();
  await expect(card).toHaveCount(0);
  await page.goto(`/games/${gameId}?node=${decision.id}`);
  await expect(
    page.getByText('我当时考虑立即出马', { exact: true }),
  ).toBeVisible();
  for (const white of [first, second]) {
    await page.goto('/games');
    const row = page.getByRole('listitem').filter({ hasText: white });
    await row.getByRole('button', { name: '归档' }).click();
    await expect(row).toHaveCount(0);
    await page.getByRole('button', { name: '已归档' }).click();
    await row.getByRole('button', { name: '永久删除' }).click();
    await page
      .getByRole('dialog')
      .getByRole('button', { name: '确认永久删除' })
      .click();
    await expect(row).toHaveCount(0);
  }
  expect((await request.get('/api/notebook/games/' + gameId)).status()).toBe(
    404,
  );
});
