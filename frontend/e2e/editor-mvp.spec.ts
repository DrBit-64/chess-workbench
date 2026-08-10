import AxeBuilder from '@axe-core/playwright';
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from '@playwright/test';

const CUSTOM_FEN = '8/8/8/8/8/3k4/8/3K4 w - - 0 1';
const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

async function postJson(
  request: APIRequestContext,
  url: string,
  data: Record<string, unknown>,
) {
  const response = await request.post(url, { data });
  expect(
    response.ok(),
    `${response.status()} ${await response.text()}`,
  ).toBeTruthy();
  return (await response.json()) as Record<string, unknown>;
}

async function move(
  request: APIRequestContext,
  parentId: string,
  uci: string,
  sortOrder: number,
) {
  return postJson(request, '/api/occurrences', {
    kind: 'move',
    parent_occurrence_id: parentId,
    uci,
    sort_order: sortOrder,
  });
}

async function clickMove(page: Page, from: string, to: string) {
  const sourceSquare = page.locator(`[data-square="${from}"]`);
  const target = page.locator(`[data-square="${to}"]`);
  await expect(sourceSquare).toBeVisible();
  await expect(target).toBeVisible();
  const response = page.waitForResponse(
    (item) =>
      item.url().endsWith('/api/occurrences') &&
      item.request().method() === 'POST',
    { timeout: 10_000 },
  );
  await sourceSquare.click();
  await expect
    .poll(() =>
      target
        .locator(':scope > div')
        .evaluate((element) => getComputedStyle(element).backgroundImage),
    )
    .toContain('radial-gradient');
  await target.click();
  expect((await response).status()).toBe(201);
}

async function keyboardMove(page: Page, uci: string) {
  const input = page.getByLabel('键盘输入着法 UCI');
  await input.fill(uci);
  const response = page.waitForResponse(
    (item) =>
      item.url().endsWith('/api/occurrences') &&
      item.request().method() === 'POST',
    { timeout: 10_000 },
  );
  await input.press('Enter');
  expect((await response).status()).toBe(201);
}

async function openTraditionalEditing(page: Page) {
  await page.getByRole('button', { name: /编\s*辑/ }).click();
  await expect(page.getByLabel('Markdown 说明')).toBeVisible();
}

test('editor MVP persists branches, citations, failures, transpositions, and PGN', async ({
  page,
  request,
}) => {
  await page.goto('/sources');
  await page.getByRole('button', { name: '添加手工来源' }).click();
  await page.getByLabel('标题').fill('E2E 手工来源');
  await page.getByRole('button', { name: /^添\s*加$/ }).click();
  await expect(page.getByText('E2E 手工来源')).toBeVisible();

  await page.goto('/learn');
  await page.getByRole('button', { name: '新建课程' }).click();
  await page.getByLabel('课程名称').fill('E2E 编辑器课程');
  await page.getByRole('button', { name: /^创\s*建$/ }).click();
  const courseLink = page.getByRole('link', { name: /E2E 编辑器课程/ });
  await expect(courseLink).toBeVisible();
  const courseHref = await courseLink.getAttribute('href');
  expect(courseHref).toMatch(/^\/learn\/[0-9a-f-]+$/);
  const courseId = courseHref!.split('/').at(-1)!;
  await courseLink.click();

  await page.getByRole('button', { name: '新建章节' }).click();
  await page.getByLabel('章节名称').fill('主线章节');
  await page.getByRole('button', { name: /^创\s*建$/ }).click();
  await expect(page.getByRole('button', { name: '主线章节' })).toBeVisible();

  await page.getByRole('button', { name: '新建章节' }).click();
  await page.getByLabel('章节名称').fill('嵌套自定义局面');
  await page.getByLabel('上级章节（可选）').click();
  await page.getByText('主线章节', { exact: true }).last().click();
  await page.getByLabel('起始 FEN').fill(CUSTOM_FEN);
  await page.getByRole('button', { name: /^创\s*建$/ }).click();
  await expect(
    page.getByRole('button', { name: /嵌套自定义局面/ }),
  ).toBeVisible();
  await page.getByRole('button', { name: /嵌套自定义局面/ }).click();
  await expect(page.getByText(CUSTOM_FEN, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '主线章节' }).click();

  const modulesResponse = await request.get(`/api/courses/${courseId}/modules`);
  expect(modulesResponse.ok()).toBeTruthy();
  const modules = (await modulesResponse.json()) as Array<
    Record<string, unknown>
  >;
  const mainModule = modules.find((item) => item.title === '主线章节')!;
  const nestedModule = modules.find((item) => item.title === '嵌套自定义局面')!;
  expect(nestedModule.parent_id).toBe(mainModule.id);
  const moduleId = String(mainModule.id);
  const rootId = String(mainModule.start_occurrence_id);

  await openTraditionalEditing(page);
  await page.getByRole('button', { name: '添加叙述正文' }).click();
  await page
    .getByLabel('叙述正文 Markdown')
    .fill('E2E **不绑定局面的章节叙述**');
  await page.getByLabel('叙述正文来源').click();
  await page.getByText('E2E 手工来源', { exact: true }).last().click();
  await page.getByRole('button', { name: '添加到本章' }).click();
  await expect(page.getByText('不绑定局面的章节叙述')).toBeVisible();

  await clickMove(page, 'e2', 'e4');
  await expect(page.getByRole('button', { name: /^e4$/ })).toBeVisible();
  await page.getByLabel('Markdown 说明').fill('E2E **着法说明**');
  await page.getByLabel('关联来源').click();
  await page.getByText('E2E 手工来源', { exact: true }).last().click();
  await page.getByRole('button', { name: /保存说明/ }).click();
  await expect(page.getByText('已与服务器同步')).toBeVisible();
  await page.getByRole('button', { name: /^起\s*点$/ }).click();
  await keyboardMove(page, 'd2d4');
  await expect(page.getByRole('button', { name: /^d4$/ })).toBeVisible();
  await page.getByRole('button', { name: /^起\s*点$/ }).click();
  await expect(page.getByRole('button', { name: /d4 d2d4/ })).toBeVisible();

  const invalid = await request.post('/api/occurrences', {
    data: {
      kind: 'move',
      parent_occurrence_id: rootId,
      uci: 'e2e5',
      sort_order: 2,
    },
  });
  expect(invalid.status()).toBe(422);
  await page.reload();
  await expect(page.getByRole('button', { name: /e5 e2e5/ })).toHaveCount(0);

  const nf3 = await move(request, rootId, 'g1f3', 2);
  const nf6AfterNf3 = await move(request, String(nf3.id), 'g8f6', 0);
  const g3Leaf = await move(request, String(nf6AfterNf3.id), 'g2g3', 0);
  const g3 = await move(request, rootId, 'g2g3', 3);
  const nf6AfterG3 = await move(request, String(g3.id), 'g8f6', 0);
  const nf3Leaf = await move(request, String(nf6AfterG3.id), 'g1f3', 0);
  expect(g3Leaf.position_id).toBe(nf3Leaf.position_id);
  await page.reload();
  await openTraditionalEditing(page);
  await page.getByRole('button', { name: /Nf3 g1f3/ }).click();
  await page.getByRole('button', { name: /Nf6 g8f6/ }).click();
  await page.getByRole('button', { name: /g3 g2g3/ }).click();
  await expect(page.getByText('转置 × 2')).toBeVisible();
  await page.getByRole('button', { name: /^起\s*点$/ }).click();

  await page.getByLabel('Markdown 说明').fill('E2E **持久化说明**');
  await page.getByLabel('关联来源').click();
  await page.getByText('E2E 手工来源', { exact: true }).last().click();
  await page.getByRole('button', { name: /保存说明/ }).click();
  await expect(page.getByText('已与服务器同步')).toBeVisible();

  await page.reload();
  await openTraditionalEditing(page);
  await expect(page.getByLabel('Markdown 说明')).toHaveValue(
    'E2E **持久化说明**',
  );
  const chapterReader = page.getByRole('article', { name: '章节正文' });
  await expect(
    chapterReader.getByText('E2E 手工来源', { exact: true }).first(),
  ).toBeVisible();
  await expect(
    chapterReader.getByText('持久化说明', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: /e4 e2e4/ }).click();
  await expect(page.getByLabel('Markdown 说明')).toHaveValue(
    'E2E **着法说明**',
  );
  await page.getByRole('button', { name: /^起\s*点$/ }).click();
  await expect(page.getByLabel('Markdown 说明')).toHaveValue(
    'E2E **持久化说明**',
  );

  await page.getByLabel('Markdown 说明').fill('断网后仍保留的草稿');
  await page.route('**/api/knowledge-notes/*', (route) =>
    route.abort('failed'),
  );
  await page.getByRole('button', { name: /保存说明/ }).click();
  await expect(page.getByText('说明尚未保存')).toBeVisible();
  await expect(page.getByLabel('Markdown 说明')).toHaveValue(
    '断网后仍保留的草稿',
  );
  await page.unroute('**/api/knowledge-notes/*');
  await page.getByRole('button', { name: /^重\s*试$/ }).click();
  await expect(page.getByText('已与服务器同步')).toBeVisible();

  const pgn = await request.get(
    `/api/courses/${courseId}/pgn?module_id=${moduleId}`,
  );
  expect(pgn.ok()).toBeTruthy();
  const pgnText = await pgn.text();
  expect(pgnText).toContain('1. e4');
  expect(pgnText).toContain('( 1. d4');

  const secondSourceModule = await postJson(request, '/api/course-modules', {
    course_id: courseId,
    title: '第二来源章节',
    start_fen: START_FEN,
    sort_order: 2,
  });
  const secondE4 = await move(
    request,
    String(secondSourceModule.start_occurrence_id),
    'e2e4',
    0,
  );
  await move(request, String(secondE4.id), 'c7c5', 0);
  const explorer = await postJson(request, '/api/courses', {
    title: 'E2E 合并探索器',
    mode: 'opening_explorer',
  });
  const explorerModule = await postJson(request, '/api/course-modules', {
    course_id: explorer.id,
    title: '旧式可见目录名',
    start_fen: START_FEN,
    sort_order: 0,
  });
  const publication = await postJson(
    request,
    `/api/courses/${String(explorer.id)}/publish-modules`,
    { module_ids: [moduleId, secondSourceModule.id] },
  );
  const publications = publication.publications as Array<
    Record<string, unknown>
  >;
  expect(publications).toHaveLength(2);
  expect(publications[0].target_module_id).toBe(explorerModule.id);
  expect(publications[1].target_module_id).toBe(explorerModule.id);
  const explorerModules = (await (
    await request.get(`/api/courses/${String(explorer.id)}/modules`)
  ).json()) as Array<Record<string, unknown>>;
  expect(explorerModules).toHaveLength(1);

  await page.goto(`/learn/${String(explorer.id)}`);
  await expect(page.getByText('合并探索图')).toBeVisible();
  await expect(page.getByText('主线章节', { exact: true })).toHaveCount(0);
  await expect(page.getByText('第二来源章节', { exact: true })).toHaveCount(0);
  await expect(page.getByText('旧式可见目录名', { exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByRole('button', { name: /e4 e2e4/ })).toHaveCount(1);
  await page.getByRole('button', { name: /e4 e2e4/ }).click();
  await expect(page.getByRole('button', { name: /c5 c7c5/ })).toBeVisible();
  await expect(page.getByText('着法说明', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '查看原文上下文' }).click();
  await expect(page.getByText('不绑定局面的章节叙述')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('heading', { name: '原文上下文' })).toBeHidden();

  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(
    accessibility.violations.filter((item) =>
      ['serious', 'critical'].includes(item.impact ?? ''),
    ),
  ).toEqual([]);

  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(page.getByLabel('Markdown 说明')).toBeVisible();
  }

  await page.getByLabel('Markdown 说明').focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('combobox', { name: '关联来源' })).toBeFocused();
});
