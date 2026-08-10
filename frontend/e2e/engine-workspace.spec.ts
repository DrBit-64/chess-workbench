import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

async function clickBoardMove(page: Page, from: string, to: string) {
  const response = page.waitForResponse(
    (item) =>
      /\/api\/engine\/games\/[0-9a-f-]+\/moves$/.test(item.url()) &&
      item.request().method() === 'POST',
  );
  await page.locator(`[data-square="${from}"]`).click();
  await page.locator(`[data-square="${to}"]`).click();
  expect((await response).status()).toBe(200);
}

test('engine workspace analyzes, queues, plays, reviews, and saves a draft', async ({
  page,
}) => {
  await page.goto('/analysis');
  await expect(page.getByRole('heading', { name: '引擎工作台' })).toBeVisible();
  await expect(page.getByText('FakeFish 1.2')).toBeVisible();

  const analysisResponse = page.waitForResponse(
    (item) =>
      item.url().endsWith('/api/engine/analyses') &&
      item.request().method() === 'POST',
  );
  await page.getByRole('button', { name: /^分\s*析$/ }).click();
  expect((await analysisResponse).status()).toBe(200);
  await expect(page.locator('.pv-row')).toHaveCount(4);
  await expect(page.locator('.pv-row').first()).toContainText('+0.34');
  await expect(page.locator('.pv-row').first()).toContainText('e4 e5 Nf3');

  await page.getByRole('button', { name: /设\s*置/ }).click();
  await expect(page.getByText('线路：4')).toBeVisible();
  await expect(page.getByText('线程：1')).toBeVisible();
  await expect(page.getByText('内存：128 MB')).toBeVisible();
  await expect(page.getByText('Ponder 关闭')).toBeVisible();
  await page.keyboard.press('Escape');

  await page.getByRole('button', { name: '后台深度分析' }).click();
  await expect(page.getByText('succeeded', { exact: true })).toBeVisible({
    timeout: 10_000,
  });

  await page.getByText('指定局面对弈', { exact: true }).click();
  await page.getByRole('button', { name: '从当前局面开始' }).click();
  await expect(page.getByText('强度 5/8')).toBeVisible();
  await clickBoardMove(page, 'e2', 'e4');
  await expect(page.getByText('1. e4')).toBeVisible();
  await expect(page.getByText('2. e5')).toBeVisible();

  await page.getByRole('button', { name: '复盘我的决策' }).click();
  await expect(page.getByText(/第 1 ply/)).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: '保存为课程草稿' }).click();
  await expect(page).toHaveURL(/\/learn\/[0-9a-f-]+$/);
  await expect(page.getByText('Human review required')).toBeVisible();

  const courseAnalysisResponse = page.waitForResponse(
    (item) =>
      item.url().endsWith('/api/engine/analyses') &&
      item.request().method() === 'POST',
  );
  await page.getByRole('switch', { name: '课程实时引擎分析' }).click();
  expect((await courseAnalysisResponse).status()).toBe(200);
  await expect(page.locator('.course-pv-row')).toHaveCount(4);
  await expect(page.locator('.course-pv-row').first()).toContainText('+0.34');
  await page.getByRole('button', { name: '课程引擎设置' }).click();
  await expect(page.getByText('分析线路：4')).toBeVisible();
  await expect(page.getByText('推荐箭头：3')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(
    page.getByRole('dialog', { name: '课程棋盘引擎设置' }),
  ).toBeHidden();

  const courseAccessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(
    courseAccessibility.violations.filter((item) =>
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
  }

  await page.goto('/analysis');
  await page.getByLabel('分析局面 FEN').fill('7k/6Q1/6K1/8/8/8/8/8 b - - 0 1');
  await page.getByRole('button', { name: '载入 FEN' }).click();
  await page.getByText('指定局面对弈', { exact: true }).click();
  await page.getByRole('button', { name: '从当前局面开始' }).click();
  await expect(page.getByText('finished', { exact: true })).toBeVisible();

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
  }
});
