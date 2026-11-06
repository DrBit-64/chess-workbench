import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';

import type { AnalysisLine } from '../logic/api/engineTypes';
import { boardOutcome } from './chapterEnginePositions';
import { CourseEvaluationBar } from './CourseEvaluationBar';

const line: AnalysisLine = {
  rank: 1,
  score_cp: 100,
  mate: null,
  wdl: null,
  uci: [],
  san: [],
};

it('shows known board results and keeps a claimable draw open for analysis', () => {
  function bar(fen: string, orientation: 'white' | 'black') {
    return (
      <CourseEvaluationBar
        outcome={boardOutcome(fen)}
        orientation={orientation}
      />
    );
  }
  const { rerender } = render(
    bar('7k/6Q1/5K2/8/8/8/8/8 b - - 150 76', 'white'),
  );
  expect(
    screen
      .getByRole('meter', { name: '棋局结果' })
      .getAttribute('aria-valuenow'),
  ).toBe('100');
  expect(screen.getByText('1–0').getAttribute('data-edge')).toBe('bottom');
  rerender(bar('8/8/8/8/8/5k2/6q1/7K w - - 0 1', 'black'));
  expect(screen.getByText('0–1').getAttribute('data-edge')).toBe('bottom');
  for (const fen of [
    '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1',
    '7k/8/8/8/8/8/8/K7 b - - 0 1',
    '7k/8/8/8/8/8/R7/K7 w - - 150 76',
  ]) {
    rerender(bar(fen, 'white'));
    expect(screen.getByRole('meter').getAttribute('aria-valuetext')).toBe(
      '和棋',
    );
    expect(screen.getByText('½–½')).toBeTruthy();
  }
  expect(boardOutcome('7k/8/8/8/8/8/R7/K7 w - - 100 73')).toBeUndefined();
});

it('keeps the evaluation white-relative while flipping the two sides', () => {
  const { rerender } = render(
    <CourseEvaluationBar line={line} orientation="white" />,
  );
  expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBe('59');
  expect(screen.getByText('+1.00').getAttribute('data-edge')).toBe('bottom');
  rerender(<CourseEvaluationBar line={line} orientation="black" />);
  expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBe('59');
  expect(screen.getByText('+1.00').getAttribute('data-edge')).toBe('top');
});

it('distinguishes a missing score from a drawn tablebase or a forced mate', () => {
  const { rerender } = render(<CourseEvaluationBar orientation="white" />);
  expect(screen.queryByRole('meter')).toBeNull();
  expect(screen.getByLabelText('当前局面暂无引擎评分')).toBeTruthy();
  rerender(
    <CourseEvaluationBar
      line={{ ...line, score_cp: null, wdl: [0, 1000, 0] }}
      orientation="white"
    />,
  );
  expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBe('50');
  expect(screen.getByText('和棋')).toBeTruthy();
  rerender(
    <CourseEvaluationBar
      line={{ ...line, score_cp: null, mate: -3 }}
      orientation="white"
    />,
  );
  expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBe('0');
  expect(screen.getByText('#-3').getAttribute('data-edge')).toBe('top');
});
