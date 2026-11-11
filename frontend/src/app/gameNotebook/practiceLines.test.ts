import { Chess } from 'chess.js';
import { describe, expect, it } from 'vitest';
import { lineNotation, parseAnswerLines, advanceAnswer } from './practiceLines';

describe('authored bookmark exercises', () => {
  it('replays alternatives from the original turn, with legal automatic replies', () => {
    const game = new Chess();
    game.move('d4');
    const start = game.fen();
    const lines = parseAnswerLines(start, '1...Nf6 2.c4 g6\n1...d5');
    expect(lineNotation(start, lines[0])).toBe('1... Nf6 2. c4 g6');
    expect(advanceAnswer(lines, [], 'e7e5')).toBeNull();
    const first = advanceAnswer(lines, [], 'g8f6')!;
    expect(first).toEqual({ moves: ['g8f6', 'c2c4'], finished: false });
    expect(advanceAnswer(lines, first.moves, 'g7g6')?.finished).toBe(true);
    expect(advanceAnswer(lines, [], 'd7d5')?.finished).toBe(true);
    expect(() => parseAnswerLines(start, 'e4')).toThrow('合法走法');
  });
});
