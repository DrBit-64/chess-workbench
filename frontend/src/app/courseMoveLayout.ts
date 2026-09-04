import type { ModuleEditor } from '../logic/api/types';
import { parentheticalVariationRoots } from './variationPresentation';

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
  const inputOrder = new Map(
    occurrences.map((occurrence, index) => [occurrence.id, index]),
  );
  const byId = new Map(
    occurrences.map((occurrence) => [occurrence.id, occurrence]),
  );
  const children = new Map<string, CourseOccurrence[]>();
  for (const occurrence of occurrences) {
    if (occurrence.parent_id === null) continue;
    const siblings = children.get(occurrence.parent_id) ?? [];
    siblings.push(occurrence);
    children.set(occurrence.parent_id, siblings);
  }
  for (const siblings of children.values()) {
    siblings.sort(
      (left, right) =>
        left.sort_order - right.sort_order ||
        (inputOrder.get(left.id) ?? 0) - (inputOrder.get(right.id) ?? 0),
    );
  }
  const parentheticalRoots = parentheticalVariationRoots(
    occurrences.map((occurrence) => ({
      id: occurrence.id,
      parentId: occurrence.parent_id,
      order: occurrence.sort_order,
    })),
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

  const primaryLine = (parentId: string): CourseMoveView[] => {
    const result: CourseMoveView[] = [];
    const visited = new Set<string>();
    let parent = parentId;
    while (!visited.has(parent)) {
      visited.add(parent);
      const primary = children.get(parent)?.[0];
      if (!primary) break;
      result.push(moveView(primary));
      parent = primary.id;
    }
    return result;
  };

  const variationsByParent = new Map<string, CourseVariation[]>();
  const indexed = new Set<string>();
  function indexTree(parentId: string, parentPath: string[]) {
    if (indexed.has(parentId)) return;
    indexed.add(parentId);
    const siblings = children.get(parentId) ?? [];
    const alternatives = siblings.slice(1).map((root) => {
      const path = [...parentPath, root.id];
      return {
        key: path.join('/'),
        depth: path.length,
        path,
        moves: [moveView(root), ...primaryLine(root.id)],
        presentation:
          path.length > 1 && parentheticalRoots.has(root.id)
            ? ('parenthetical' as const)
            : ('rail' as const),
      };
    });
    if (alternatives.length > 0) variationsByParent.set(parentId, alternatives);

    siblings.forEach((child, index) => {
      const childPath = index === 0 ? parentPath : [...parentPath, child.id];
      indexTree(child.id, childPath);
    });
  }
  indexTree(rootId, []);

  const mainline = primaryLine(rootId);
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
