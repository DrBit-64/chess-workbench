import type { PdfReviewDocument } from '../logic/api/types';

type ReviewItem = NonNullable<PdfReviewDocument['package']['items']>[number];
type MoveSequenceItem = Extract<ReviewItem, { kind: 'move_sequence' }>;

export type MoveNode = MoveSequenceItem['nodes'][number];

export interface ReviewMoveRow {
  /** Stable row key built from the contained node ids. */
  key: string;
  /** Uncapped alternative-branch depth (0 = mainline). */
  variationDepth: number;
  /** Fullmove number for the gutter; null for fallback rows. */
  moveNumber: number | null;
  /** White ply node, or null for black-only rows. */
  white: MoveNode | null;
  /** Black ply node, or null for white-only rows. */
  black: MoveNode | null;
  /** Full-width fallback node (null side or move number). */
  fallback: MoveNode | null;
  /** Ordered first-seen union of the contained node evidence pages. */
  evidencePages: number[];
}

/**
 * Project a normalized move sequence into conventional two-ply score rows.
 *
 * Nodes are consumed exactly once in their existing array order and never
 * mutated, sorted or deduplicated. Indentation reflects only actual
 * alternative branches: a child inherits its parent's variation depth and
 * increases it solely when its own `sibling_order > 0`; an arbitrarily long
 * primary line therefore never indents. Flattening every row's
 * white/black/fallback nodes in visual order reproduces the exact input array
 * by object identity.
 */
export function buildReviewMoveRows(nodes: MoveNode[]): ReviewMoveRow[] {
  const depths = variationDepths(nodes);
  const rows: ReviewMoveRow[] = [];
  let pendingWhite: MoveNode | null = null;
  let pendingWhiteDepth = 0;
  let pendingWhiteMoveNumber: number | null = null;

  function flushWhite() {
    if (pendingWhite !== null) {
      rows.push(
        makeRow(pendingWhite, null, pendingWhiteDepth, pendingWhiteMoveNumber),
      );
      pendingWhite = null;
    }
  }

  for (const node of nodes) {
    const depth = depths.get(node.id) ?? 0;
    const moveNumber = node.move_number;
    const side = node.side_to_move;

    if (side === null || moveNumber === null) {
      flushWhite();
      rows.push(makeRow(null, null, depth, moveNumber, node));
      continue;
    }

    if (side === 'w') {
      flushWhite();
      pendingWhite = node;
      pendingWhiteDepth = depth;
      pendingWhiteMoveNumber = moveNumber;
      continue;
    }

    const canPair =
      pendingWhite !== null &&
      pendingWhiteMoveNumber === moveNumber &&
      node.parent_id === pendingWhite.id &&
      node.sibling_order === 0 &&
      depth === pendingWhiteDepth;
    if (canPair) {
      rows.push(makeRow(pendingWhite, node, depth, moveNumber));
      pendingWhite = null;
    } else {
      flushWhite();
      rows.push(makeRow(null, node, depth, moveNumber));
    }
  }

  flushWhite();
  return rows;
}

/** Topological variation depth: parent-before-child by CCEF contract. */
function variationDepths(nodes: MoveNode[]): Map<string, number> {
  const depths = new Map<string, number>();
  for (const node of nodes) {
    if (node.parent_id === null) {
      depths.set(node.id, node.sibling_order === 0 ? 0 : 1);
    } else {
      const parentDepth = depths.get(node.parent_id);
      const base = parentDepth === undefined ? 0 : parentDepth;
      depths.set(node.id, node.sibling_order > 0 ? base + 1 : base);
    }
  }
  return depths;
}

function makeRow(
  white: MoveNode | null,
  black: MoveNode | null,
  depth: number,
  moveNumber: number | null,
  fallback: MoveNode | null = null,
): ReviewMoveRow {
  const contained = [fallback, white, black].filter(
    (node): node is MoveNode => node !== null,
  );
  const pages: number[] = [];
  for (const node of contained) {
    for (const ref of node.evidence) {
      if (!pages.includes(ref.page)) {
        pages.push(ref.page);
      }
    }
  }
  return {
    key: contained.map((node) => node.id).join('+'),
    variationDepth: depth,
    moveNumber,
    white,
    black,
    fallback,
    evidencePages: pages,
  };
}
