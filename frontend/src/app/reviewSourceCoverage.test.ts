import { describe, expect, it } from 'vitest';
import type { PdfSourceEvidence } from '../logic/api/types';
import {
  buildReviewSourceIndex,
  paragraphCoverage,
  type SourceReviewItem,
} from './reviewSourceCoverage';

type Sequence = Extract<SourceReviewItem, { kind: 'move_sequence' }>;
const hash = 'a'.repeat(64);
const text = '😀 1 e4 e5 (1 e4) on h3';
const ref = (start: number, end: number) => ({
  page: 1,
  fragment_sha256: hash,
  start_offset: start,
  end_offset: end,
  bbox: null,
});
const source: PdfSourceEvidence = {
  run_id: 'test',
  first_page: 1,
  last_page: 1,
  evidence_status: 'ready',
  error_code: null,
  pages: [
    {
      physical_page: 1,
      fragments: [
        {
          order: 0,
          text,
          origin: 'embedded_text',
          bbox: {},
          fragment_sha256: hash,
          roles: [],
          move_mentions: [
            { start: 4, end: 6, kind: 'candidate' },
            { start: 7, end: 9, kind: 'candidate' },
            { start: 13, end: 15, kind: 'candidate' },
            { start: 20, end: 22, kind: 'square' },
          ],
        },
      ],
    },
  ],
};
function sequence(): Sequence {
  return {
    kind: 'move_sequence',
    id: 'score',
    title: null,
    initial_position: { kind: 'startpos' },
    evidence: [],
    confidence: null,
    nodes: [
      {
        id: 'move',
        parent_id: null,
        sibling_order: 0,
        move_text: 'e4',
        san_candidate: 'e4',
        uci_candidate: 'e2e4',
        fen_before: null,
        fen_after: 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1',
        side_to_move: 'w',
        move_number: 1,
        nags: [],
        validation_status: 'valid',
        evidence: [ref(4, 6)],
        confidence: null,
      },
    ],
  };
}

describe('current-review source coverage', () => {
  it('keeps repeated SAN occurrences separate and follows deletion and restoration', () => {
    const game = sequence();
    const check = (items: SourceReviewItem[]) =>
      paragraphCoverage(
        text,
        [ref(0, 22)],
        buildReviewSourceIndex(items, source),
      )!;
    const before = check([game]);
    expect(before.recorded).toBe(1);
    expect(before.pending).toBe(2);
    expect(before.mentions.map((m) => text.slice(m.start, m.end))).toEqual([
      'e4',
      'e5',
      'e4',
    ]);
    expect(before.mentions[0].target).toEqual({
      sequenceId: 'score',
      nodeId: 'move',
    });
    expect(check([]).pending).toBe(3);
    expect(check([game]).recorded).toBe(1);
    // Broad manual evidence cannot prove which of the two e4 occurrences it means.
    game.nodes[0].evidence = [ref(0, 22)];
    expect(check([game]).recorded).toBe(0);
    expect(
      paragraphCoverage(
        'Edited 1 e4',
        [ref(0, 22)],
        buildReviewSourceIndex([game], source),
      )?.unaligned,
    ).toBe(true);
  });
});
