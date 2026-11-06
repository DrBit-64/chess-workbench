import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';

import type { AnalysisLine } from '../logic/api/engineTypes';
import { CourseEvaluationBar } from './CourseEvaluationBar';

const line: AnalysisLine = {
  rank: 1,
  score_cp: 100,
  mate: null,
  wdl: null,
  uci: [],
  san: [],
};

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
