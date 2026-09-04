import type { PdfReviewDocument } from '../logic/api/types';
import { parentheticalVariationRoots } from './variationPresentation';

type ReviewItem = NonNullable<PdfReviewDocument['package']['items']>[number];
type MoveSequenceItem = Extract<ReviewItem, { kind: 'move_sequence' }>;
type V1_1Package = Extract<
  PdfReviewDocument['package'],
  { schema_version: 'chess-content-extraction/1.1' }
>;
export type AnnotatedMoveSequenceItem = Extract<
  NonNullable<V1_1Package['items']>[number],
  { kind: 'move_sequence' }
>;

export type MoveNode = MoveSequenceItem['nodes'][number];
export type SequenceAnnotation = NonNullable<
  AnnotatedMoveSequenceItem['annotations']
>[number];

export interface ReviewMoveRow {
  /** Stable row key built from the contained node ids. */
  key: string;
  /** Uncapped alternative-branch depth (0 = mainline). */
  variationDepth: number;
  /** Ordered alternative roots from the outermost branch to this row. */
  variationPath: string[];
  /** Compact Lichess-style parentheses or an explicit branch rail. */
  variationPresentation: 'mainline' | 'parenthetical' | 'rail';
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

export type ReviewReadingBlock =
  | { kind: 'move_row'; key: string; row: ReviewMoveRow }
  | {
      kind: 'annotation';
      key: string;
      annotation: SequenceAnnotation;
      variationDepth: number;
      variationPath: string[];
      variationPresentation: 'mainline' | 'parenthetical' | 'rail';
    };

export type CompactReviewBlock =
  | { kind: 'mainline_row'; key: string; row: ReviewMoveRow }
  | {
      kind: 'variation_line';
      key: string;
      variationDepth: number;
      variationPath: string[];
      presentation: 'parenthetical' | 'rail';
      rows: ReviewMoveRow[];
    }
  | Extract<ReviewReadingBlock, { kind: 'annotation' }>;

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
  const paths = variationPaths(nodes);
  const parentheticalRoots = reviewParentheticalRoots(nodes);
  return buildMoveRowsWithPaths(nodes, paths, parentheticalRoots);
}

/**
 * Project a CCEF 1.1 reading flow into move rows interleaved with annotations.
 *
 * Topology remains authoritative for variation depth, while reading_flow is
 * authoritative for presentation. An annotation flushes a pending half-row,
 * so notes can genuinely interrupt a main line before it resumes.
 */
export function buildReviewReadingFlow(
  item: AnnotatedMoveSequenceItem,
): ReviewReadingBlock[] {
  const paths = variationPaths(item.nodes);
  const parentheticalRoots = reviewParentheticalRoots(item.nodes);
  const nodes = new Map(item.nodes.map((node) => [node.id, node]));
  const annotations = new Map(
    (item.annotations ?? []).map((annotation) => [annotation.id, annotation]),
  );
  const blocks: ReviewReadingBlock[] = [];
  let bufferedMoves: MoveNode[] = [];

  function flushMoves() {
    for (const row of buildMoveRowsWithPaths(
      bufferedMoves,
      paths,
      parentheticalRoots,
    )) {
      blocks.push({ kind: 'move_row', key: `move:${row.key}`, row });
    }
    bufferedMoves = [];
  }

  for (const entry of item.reading_flow) {
    if (entry.kind === 'move') {
      const node = nodes.get(entry.node_id);
      if (node === undefined) {
        throw new Error('review reading flow contains an unknown move');
      }
      bufferedMoves.push(node);
      continue;
    }

    flushMoves();
    const annotation = annotations.get(entry.annotation_id);
    if (annotation === undefined) {
      throw new Error('review reading flow contains an unknown annotation');
    }
    const variationPath =
      annotation.anchor?.kind === 'move_node'
        ? (paths.get(annotation.anchor.node_id) ?? [])
        : [];
    blocks.push({
      kind: 'annotation',
      key: `annotation:${annotation.id}`,
      annotation,
      variationDepth: variationPath.length,
      variationPath,
      variationPresentation: presentationForPath(
        variationPath,
        parentheticalRoots,
      ),
    });
  }
  flushMoves();
  return blocks;
}

/** Group adjacent rows of one real variation into a dense inline line. */
export function compactReviewBlocks(
  blocks: ReviewReadingBlock[],
): CompactReviewBlock[] {
  const compact: CompactReviewBlock[] = [];
  let pendingRows: ReviewMoveRow[] = [];
  let pendingPath: string[] = [];

  function flushVariation() {
    if (pendingRows.length === 0) return;
    compact.push({
      kind: 'variation_line',
      key: `variation:${pendingPath.join('/')}:${pendingRows
        .map((row) => row.key)
        .join('+')}`,
      variationDepth: pendingPath.length,
      variationPath: pendingPath,
      presentation:
        pendingRows[0]?.variationPresentation === 'parenthetical'
          ? 'parenthetical'
          : 'rail',
      rows: pendingRows,
    });
    pendingRows = [];
    pendingPath = [];
  }

  for (const block of blocks) {
    if (block.kind === 'annotation') {
      flushVariation();
      compact.push(block);
    } else if (block.row.variationDepth === 0) {
      flushVariation();
      compact.push({ kind: 'mainline_row', key: block.key, row: block.row });
    } else if (
      pendingRows.length > 0 &&
      samePath(pendingPath, block.row.variationPath)
    ) {
      pendingRows.push(block.row);
    } else {
      flushVariation();
      pendingRows = [block.row];
      pendingPath = block.row.variationPath;
    }
  }
  flushVariation();
  return compact;
}

function buildMoveRowsWithPaths(
  nodes: MoveNode[],
  paths: Map<string, string[]>,
  parentheticalRoots: ReadonlySet<string>,
): ReviewMoveRow[] {
  const rows: ReviewMoveRow[] = [];
  let pendingWhite: MoveNode | null = null;
  let pendingWhitePath: string[] = [];
  let pendingWhiteMoveNumber: number | null = null;

  function flushWhite() {
    if (pendingWhite !== null) {
      rows.push(
        makeRow(
          pendingWhite,
          null,
          pendingWhitePath,
          parentheticalRoots,
          pendingWhiteMoveNumber,
        ),
      );
      pendingWhite = null;
    }
  }

  for (const node of nodes) {
    const path = paths.get(node.id) ?? [];
    const moveNumber = node.move_number;
    const side = node.side_to_move;

    if (side === null || moveNumber === null) {
      flushWhite();
      rows.push(
        makeRow(null, null, path, parentheticalRoots, moveNumber, node),
      );
      continue;
    }

    if (side === 'w') {
      flushWhite();
      pendingWhite = node;
      pendingWhitePath = path;
      pendingWhiteMoveNumber = moveNumber;
      continue;
    }

    const canPair =
      pendingWhite !== null &&
      pendingWhiteMoveNumber === moveNumber &&
      node.parent_id === pendingWhite.id &&
      node.sibling_order === 0 &&
      samePath(path, pendingWhitePath);
    if (canPair) {
      rows.push(
        makeRow(pendingWhite, node, path, parentheticalRoots, moveNumber),
      );
      pendingWhite = null;
    } else {
      flushWhite();
      rows.push(makeRow(null, node, path, parentheticalRoots, moveNumber));
    }
  }

  flushWhite();
  return rows;
}

/** Topological variation lineage: parent-before-child by CCEF contract. */
function variationPaths(nodes: MoveNode[]): Map<string, string[]> {
  const paths = new Map<string, string[]>();
  for (const node of nodes) {
    const parentPath =
      node.parent_id === null ? [] : (paths.get(node.parent_id) ?? []);
    paths.set(
      node.id,
      node.sibling_order > 0 ? [...parentPath, node.id] : parentPath,
    );
  }
  return paths;
}

function makeRow(
  white: MoveNode | null,
  black: MoveNode | null,
  variationPath: string[],
  parentheticalRoots: ReadonlySet<string>,
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
    variationDepth: variationPath.length,
    variationPath,
    variationPresentation: presentationForPath(
      variationPath,
      parentheticalRoots,
    ),
    moveNumber,
    white,
    black,
    fallback,
    evidencePages: pages,
  };
}

function reviewParentheticalRoots(nodes: MoveNode[]): Set<string> {
  return parentheticalVariationRoots(
    nodes.map((node) => ({
      id: node.id,
      parentId: node.parent_id,
      order: node.sibling_order,
    })),
  );
}

function presentationForPath(
  variationPath: string[],
  parentheticalRoots: ReadonlySet<string>,
): 'mainline' | 'parenthetical' | 'rail' {
  if (variationPath.length === 0) return 'mainline';
  return variationPath.length > 1 &&
    parentheticalRoots.has(variationPath[variationPath.length - 1]!)
    ? 'parenthetical'
    : 'rail';
}

function samePath(left: string[], right: string[]): boolean {
  return (
    left.length === right.length &&
    left.every((entry, index) => entry === right[index])
  );
}
