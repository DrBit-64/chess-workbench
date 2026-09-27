import type { ModuleEditor } from '../logic/api/types';
import { buildScoreTreeLayout } from './scoreTreeLayout';

export type CourseOccurrence = ModuleEditor['occurrences'][number];

export interface CourseMoveView {
  occurrence: CourseOccurrence;
  moveNumber: number;
  side: 'white' | 'black';
}

export interface CourseMoveRow {
  key: string;
  moveNumber: number;
  white: CourseMoveView | null;
  black: CourseMoveView | null;
}

export interface CourseVariation {
  key: string;
  depth: number;
  path: string[];
  moves: CourseMoveView[];
  presentation: 'parenthetical' | 'rail';
}

export interface CourseScoreLayout {
  mainline: CourseMoveView[];
  mainlineRows: CourseMoveRow[];
  variationsByParent: Map<string, CourseVariation[]>;
}

/**
 * Project the course occurrence tree into a primary line plus explicit
 * alternatives. The course graph has no reading_flow, so sort_order is the
 * only presentation priority and the original response order is the stable
 * tie-breaker.
 */
export function buildCourseScoreLayout(
  occurrences: CourseOccurrence[],
  rootId: string,
): CourseScoreLayout {
  const tree = buildScoreTreeLayout(occurrences, rootId, (occurrence) => ({
    id: occurrence.id,
    parentId: occurrence.parent_id,
    order: occurrence.sort_order,
  }));
  const byId = new Map(
    occurrences.map((occurrence) => [occurrence.id, occurrence]),
  );

  const moveView = (occurrence: CourseOccurrence): CourseMoveView => {
    const parent = occurrence.parent_id
      ? byId.get(occurrence.parent_id)
      : undefined;
    const fields = parent?.full_fen.split(/\s+/) ?? [];
    const parsed = Number.parseInt(fields[5] ?? '1', 10);
    return {
      occurrence,
      moveNumber: Number.isFinite(parsed) && parsed > 0 ? parsed : 1,
      side: fields[1] === 'b' ? 'black' : 'white',
    };
  };

  const variationsByParent = new Map<string, CourseVariation[]>();
  for (const [parentId, variations] of tree.variationsByParent) {
    if (parentId === null) continue;
    variationsByParent.set(
      parentId,
      variations.map((variation) => ({
        ...variation,
        moves: variation.moves.map(moveView),
      })),
    );
  }
  const mainline = tree.mainline.map(moveView);
  return {
    mainline,
    mainlineRows: pairCourseMoves(mainline),
    variationsByParent,
  };
}

export function pairCourseMoves(moves: CourseMoveView[]): CourseMoveRow[] {
  const rows: CourseMoveRow[] = [];
  let pendingWhite: CourseMoveView | null = null;
  for (const move of moves) {
    if (move.side === 'white') {
      if (pendingWhite !== null) rows.push(makeRow(pendingWhite, null));
      pendingWhite = move;
      continue;
    }
    if (
      pendingWhite !== null &&
      pendingWhite.moveNumber === move.moveNumber &&
      move.occurrence.parent_id === pendingWhite.occurrence.id
    ) {
      rows.push(makeRow(pendingWhite, move));
      pendingWhite = null;
    } else {
      if (pendingWhite !== null) rows.push(makeRow(pendingWhite, null));
      rows.push(makeRow(null, move));
      pendingWhite = null;
    }
  }
  if (pendingWhite !== null) rows.push(makeRow(pendingWhite, null));
  return rows;
}

function makeRow(
  white: CourseMoveView | null,
  black: CourseMoveView | null,
): CourseMoveRow {
  const move = white ?? black;
  if (move === null) throw new Error('course score row must contain a move');
  return {
    key: [white?.occurrence.id, black?.occurrence.id].filter(Boolean).join('+'),
    moveNumber: move.moveNumber,
    white,
    black,
  };
}
