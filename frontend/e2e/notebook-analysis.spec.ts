import { randomUUID } from 'node:crypto';
import {
  expect,
  test as base,
  type Locator,
  type Page,
} from '@playwright/test';

type SourceNode = {
  id: string;
  ply: number;
  fen: string;
  san: string | null;
  is_mainline: boolean;
};
type CachedScore = {
  fen: string;
  score_cp: number | null;
  mate: number | null;
};

async function bounds(locator: Locator) {
  await expect(locator).toBeVisible();
  const rect = await locator.boundingBox();
  expect(rect).not.toBeNull();
  return rect!;
}

async function fits(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
    )
    .toBeLessThanOrEqual(1);
}

type SavedGame = { white: string; gameId: string; main: SourceNode[] };

const test = base.extend<{ game: SavedGame }>({
  game: async ({ request }, runTest) => {
    const white = 'QA-' + randomUUID().slice(0, 8);
    const pgn = `[White "${white}"]
[Black "Black-QA"]
[WhiteElo "1968"]
[BlackElo "2044"]
[TimeControl "300+3"]
[Date "2026.11.12"]
[Result "1-0"]
[Opening "Misleading imported tag"]

1. e4 {[%eval 0.37]} d5 2. exd5 Nf6 (2... Qxd5 3. Nc3 (3. d4) Qa5) 3. d4 (3. c4 c6) 1-0`;
    const imported = await request.post('/api/notebook/imports', {
      data: { pgn, selections: [{ index: 0 }] },
    });
    expect(imported.ok(), await imported.text()).toBeTruthy();
    const { games } = await imported.json();
    const gameId: string = games[0].id;
    const sourceUrl = '/api/notebook/games/' + gameId;
    try {
      const { nodes }: { nodes: SourceNode[] } = await (
        await request.get(sourceUrl)
      ).json();
      const main = nodes
        .filter((n) => n.is_mainline && n.ply > 0)
        .sort((a, b) => a.ply - b.ply);
      await runTest({ white, gameId, main });
    } finally {
      const current = await request.get(sourceUrl);
      if (current.ok()) {
        const archived = await request.patch(sourceUrl, {
          data: {
            archived: true,
            expected_version: (await current.json()).version,
          },
        });
        if (archived.ok())
          await request.delete(sourceUrl, {
            params: { expected_version: (await archived.json()).version },
          });
      }
    }
  },
});

test('saved game cards link to aligned move pairs, nested variations and mobile notebook actions', async ({
  page,
  game,
}) => {
  const { white, main } = game;
  const end = main.at(-1)!;
  expect(end.fen.split(' ')[0]).toBe(
    'rnbqkb1r/ppp1pppp/5n2/3P4/3P4/8/PPP2PPP/RNBQKBNR',
  );
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/games?q=' + white);
  const card = page.getByRole('listitem').filter({ hasText: white });
  await expect(card).toContainText('1968');
  await expect(card).toContainText('2044');
  await expect(card).toContainText('Scandinavian Defense');
  await expect(card).not.toContainText('Misleading imported tag');
  await expect(card).toContainText('5+3');
  await expect(
    card.getByRole('img', { name: '实战主线的最终局面' }),
  ).toHaveAttribute('data-fen', end.fen);
  await card.getByRole('link', { name: '打开棋谱' }).click();
  const board = page.locator('.game-review-board-column');
  const score = page.locator('.game-review-score-column');
  const sidebar = page.locator('.game-review-sidebar');
  const engine = score.getByRole('region', { name: '棋谱引擎分析' });
  const boardBox = await bounds(board),
    scoreBox = await bounds(score),
    toolsBox = await bounds(sidebar);
  expect(boardBox.x + boardBox.width).toBeLessThanOrEqual(scoreBox.x + 1);
  expect(scoreBox.x + scoreBox.width).toBeLessThanOrEqual(toolsBox.x + 1);
  await fits(page);
  const row = score.locator('.nb-notation-row[data-move-number="1"]');
  const e4 = row.locator('[data-side="white"]');
  const d5 = row.locator('[data-side="black"]');
  await expect(e4).toContainText('e4');
  await expect(d5).toContainText('d5');
  await expect(e4.locator('.nb-notation-eval')).not.toHaveText('');
  const whiteBox = await bounds(e4),
    blackBox = await bounds(d5);
  expect(whiteBox.x + whiteBox.width).toBeLessThanOrEqual(blackBox.x + 1);
  expect(Math.abs(whiteBox.y - blackBox.y)).toBeLessThan(4);
  const region = await bounds(engine),
    rowBox = await bounds(row);
  expect(region.y + region.height).toBeLessThanOrEqual(rowBox.y + 1);
  const nested = score
    .locator('.nb-notation-variation[data-depth="2"]')
    .first();
  await expect(nested).toContainText('(');
  await expect(nested).toContainText(')');
  await nested.locator('button').first().click();
  await expect(score.locator('[aria-current="step"]')).toHaveAccessibleName(
    /分析变例/,
  );
  await page.reload();
  for (const size of [
    { width: 336, height: 741 },
    { width: 741, height: 228 },
  ]) {
    await page.setViewportSize(size);
    await fits(page);
    await expect(engine).toBeVisible();
    if (size.width > size.height) {
      await expect(engine).toBeInViewport();
      expect(
        (await bounds(score.locator('.game-review-score-list'))).height,
      ).toBeGreaterThanOrEqual(55);
      await expect(score.locator('[aria-current="step"]')).toBeInViewport();
    }
    await expect(
      page.getByRole('button', { name: '棋步菜单' }),
    ).toBeInViewport();
  }
  await page.getByRole('button', { name: '全屏阅读' }).click();
  await expect
    .poll(() => page.evaluate(() => !!document.fullscreenElement))
    .toBe(true);
  await page.getByRole('button', { name: '评语与收藏', exact: true }).click();
  await expect(page.getByRole('button', { name: '写棋步评语' })).toBeVisible();
  await page.getByRole('button', { name: '棋谱', exact: true }).click();
  await expect(score.locator('[aria-current="step"]')).toHaveAccessibleName(
    /分析变例/,
  );
  await page.getByRole('button', { name: '退出全屏' }).click();
});

// Opt in when the test API is running a local Stockfish with MultiPV support.
const nativeEngineTest =
  process.env.CHESS_WORKBENCH_E2E_NATIVE_ENGINE === '1' ? test : test.skip;
nativeEngineTest(
  'native engine draws the requested PV and restores each mainline score from cache',
  async ({ page, request, game }) => {
    test.setTimeout(120_000);
    const { gameId, main } = game;
    const capabilities = await (
      await request.get('/api/engine/capabilities')
    ).json();
    expect(capabilities.available).toBe(true);
    // Warm a recorded post-move position before opening the game. It must be available on load.
    const seeded = await request.post('/api/engine/analyses', {
      data: { fen: main[0].fen, parameters: capabilities.default_parameters },
    });
    expect(seeded.ok(), await seeded.text()).toBeTruthy();
    await page.goto('/games/' + gameId);
    const board = page.locator('.game-review-board-column');
    const score = page.locator('.game-review-score-column');
    const engine = score.getByRole('region', { name: '棋谱引擎分析' });
    const e4 = score.locator(`[data-notebook-node="${main[0].id}"]`);
    await e4.click();
    const expectedPvs: { lines: { uci: string[]; san: string[] }[] } =
      await seeded.json();
    const meter = board.getByRole('meter', { name: '引擎局面评分' });
    await expect(meter).toBeVisible({ timeout: 25_000 });
    const bestMove = expectedPvs.lines[0].uci[0];
    await expect(
      board.locator(
        `[data-source="engine"][data-from="${bestMove.slice(0, 2)}"][data-to="${bestMove.slice(2, 4)}"]`,
      ),
    ).toBeVisible();
    const candidates = engine.locator('summary');
    await expect(candidates).toHaveCount(expectedPvs.lines.length);
    await expect(candidates.first()).toContainText(
      '1... ' + expectedPvs.lines[0].san[0],
    );
    await candidates.first().click();
    await expect(engine.locator('details[open]').first()).toContainText(
      expectedPvs.lines[0].san.at(-1)!,
    );
    await candidates.first().click();
    const requestedFens: string[] = [];
    page.on('request', (request) => {
      if (
        request.url().endsWith('/api/engine/analyses') &&
        request.method() === 'POST'
      )
        requestedFens.push(request.postDataJSON().fen);
    });
    const batch = engine.getByRole('button', { name: '分析整盘棋谱' });
    await batch.click();
    const scores = score.locator('.nb-notation-row .nb-notation-eval');
    await expect(scores).toHaveCount(main.length, { timeout: 60_000 });
    expect(requestedFens).not.toContain(main[0].fen);
    const response = await request.post('/api/engine/analyses/cache-lookup', {
      data: {
        fens: main.map((n) => n.fen),
        parameters: capabilities.default_parameters,
        include_scores: true,
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    const { cached_scores }: { cached_scores: CachedScore[] } =
      await response.json();
    for (const n of main) {
      const saved = cached_scores.find((s) => s.fen === n.fen);
      expect(
        saved,
        `cached evaluation for ${n.san} after ply ${n.ply}`,
      ).toBeDefined();
      const label =
        saved!.mate !== null
          ? '#' + saved!.mate
          : (saved!.score_cp! >= 0 ? '+' : '') +
            (saved!.score_cp! / 100).toFixed(2);
      await expect(
        score.locator(`[data-notebook-node="${n.id}"] .nb-notation-eval`),
      ).toHaveText(label);
    }
    await page.reload();
    await expect(scores).toHaveCount(main.length);
  },
);
