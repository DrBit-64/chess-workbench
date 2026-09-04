import { describe, expect, it } from 'vitest';

import type { ModuleEditor } from '../logic/api/types';
import { buildCourseScoreLayout } from './courseMoveLayout';

type EditorOccurrence = ModuleEditor['occurrences'][number];

const rootFen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const e4Fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1';
const e4e5Fen = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2';

function occurrence(
  id: string,
  parentId: string | null,
  fen: string,
  san: string | null,
  uci: string | null,
  sortOrder = 0,
): EditorOccurrence {
  return {
    id,
    course_id: 'course-1',
    module_id: 'module-1',
    position_id: `position-${id}`,
    parent_id: parentId,
    inbound_move_edge_id: parentId === null ? null : `edge-${id}`,
    full_fen: fen,
    inbound_san: san,
    inbound_uci: uci,
    nag: null,
    sort_order: sortOrder,
    context: {},
    version: 1,
    archived_at: null,
    created_at: '2026-08-27T00:00:00Z',
    updated_at: '2026-08-27T00:00:00Z',
  };
}

describe('course move layout', () => {
  it('pairs the mainline and keeps every alternative on explicit nested paths', () => {
    const root = occurrence('root', null, rootFen, null, null);
    const e4 = occurrence('e4', 'root', e4Fen, 'e4', 'e2e4');
    const d4 = occurrence('d4', 'root', e4Fen, 'd4', 'd2d4', 1);
    const e5 = occurrence('e5', 'e4', e4e5Fen, 'e5', 'e7e5');
    const c5 = occurrence('c5', 'e4', e4e5Fen, 'c5', 'c7c5', 1);
    const nf3 = occurrence('nf3', 'e5', e4e5Fen, 'Nf3', 'g1f3');
    const nc6 = occurrence('nc6', 'c5', e4e5Fen, 'Nc6', 'b8c6');
    const d6 = occurrence('d6', 'c5', e4e5Fen, 'd6', 'd7d6', 1);

    const layout = buildCourseScoreLayout(
      [root, d6, nf3, c5, d4, e5, nc6, e4],
      root.id,
    );

    expect(
      layout.mainlineRows.map((row) => [
        row.moveNumber,
        row.white?.occurrence.id,
        row.black?.occurrence.id,
      ]),
    ).toEqual([
      [1, 'e4', 'e5'],
      [2, 'nf3', undefined],
    ]);
    expect(layout.variationsByParent.get('root')?.[0]?.path).toEqual(['d4']);
    expect(layout.variationsByParent.get('root')?.[0]?.presentation).toBe(
      'rail',
    );
    expect(layout.variationsByParent.get('e4')?.[0]?.path).toEqual(['c5']);
    // The secondary c5 line forks again within six plies, so Lichess keeps
    // the explicit rail treatment instead of parenthesizing it.
    expect(layout.variationsByParent.get('e4')?.[0]?.presentation).toBe('rail');
    expect(layout.variationsByParent.get('c5')?.[0]?.path).toEqual([
      'c5',
      'd6',
    ]);
    expect(layout.variationsByParent.get('c5')?.[0]?.presentation).toBe(
      'parenthetical',
    );
  });
});
