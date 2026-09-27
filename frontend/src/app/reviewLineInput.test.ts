import { describe, expect, it } from 'vitest';

import { parseReviewLine } from './reviewLineInput';

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

describe('parseReviewLine', () => {
  it('uses the selected position to parse printed notation and punctuation', () => {
    const result = parseReviewLine(
      '2...dXc4? 3.e4!',
      'rnbqkbnr/ppp1pppp/8/3p4/2PP4/8/PP2PPPP/RNBQKBNR b KQkq c3 0 2',
    );
    expect(result).toMatchObject({
      ok: true,
      uci: ['d5c4', 'e2e4'],
      san: ['dxc4', 'e4'],
      nags: [2, 1],
    });
  });

  it('rejects a legal move when its printed turn belongs to another position', () => {
    expect(parseReviewLine('3.e4', START)).toMatchObject({
      ok: false,
      index: 0,
      message: expect.stringContaining('来源步号 3.'),
    });
  });

  it('locates a move that cannot be played instead of preparing a partial save', () => {
    expect(parseReviewLine('1.e4 e5 2.e4', START)).toMatchObject({
      ok: false,
      index: 2,
      token: 'e4',
    });
  });
});
