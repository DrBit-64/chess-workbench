import type { PdfReviewDocument } from '../logic/api/types';
import { buildScoreTreeLayout } from './scoreTreeLayout';
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

/** Chess-tree display order, with alternatives beside their branch point. */
function visibleScoreMoves(nodes: MoveNode[]): MoveNode[] {
  const tree = buildScoreTreeLayout(nodes, null, (node) => ({
    id: node.id,
    parentId: node.parent_id,
    order: node.sibling_order,
  }));
  const ordered: MoveNode[] = [];

  function addLine(moves: MoveNode[], isVariation = false) {
    for (const [index, node] of moves.entries()) {
      ordered.push(node);
      // An alternative belongs after the move it replaces, not after their
      // shared parent. A white alternative therefore separates White's move
      // from Black's reply; uninterrupted pairs remain on the same row.
      if (!isVariation || index > 0) {
        for (const variation of tree.variationsByParent.get(node.parent_id) ??
          []) {
          addLine(variation.moves, true);
        }
      }
    }
  }
  addLine(tree.mainline);
  return ordered;
}

/** Display turn metadata from the server-validated position, including old runs. */
export function reviewMoveTurn(node: MoveNode): {
  moveNumber: number | null;
  side: 'w' | 'b' | null;
} {
  const fields =
    node.validation_status === 'valid'
      ? node.fen_before?.split(/\s+/)
      : undefined;
  const fenSide = fields?.[1];
  const fenNumber = Number(fields?.[5]);
  return {
    moveNumber:
      node.move_number ??
      (Number.isInteger(fenNumber) && fenNumber > 0 ? fenNumber : null),
    side:
      node.side_to_move ??
      (fenSide === 'w' || fenSide === 'b' ? fenSide : null),
  };
}

/** Project the chess tree into score rows; never mutate the source package. */
export function buildReviewMoveRows(nodes: MoveNode[]): ReviewMoveRow[] {
  return buildMoveRowsWithPaths(
    visibleScoreMoves(nodes),
    variationPaths(nodes),
    reviewParentheticalRoots(nodes),
  );
}

/**
 * Display a CCEF score by chess parentage while retaining source reading_flow
 * for annotation placement and publication semantics.
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
  const before = new Map<string | null, SequenceAnnotation[]>();
  const after = new Map<string | null, SequenceAnnotation[]>();
  let precedingSourceMove: string | null = null;
  for (const entry of item.reading_flow) {
    if (entry.kind === 'move') {
      precedingSourceMove = entry.node_id;
      continue;
    }
    const annotation = annotations.get(entry.annotation_id);
    if (annotation === undefined) {
      throw new Error('review reading flow contains an unknown annotation');
    }
    const anchor = annotation.anchor;
    const anchorId =
      anchor?.kind === 'move_node' && nodes.has(anchor.node_id)
        ? anchor.node_id
        : precedingSourceMove;
    const destination =
      anchor?.kind === 'move_node' && anchor.relation === 'before'
        ? before
        : after;
    const bucket = destination.get(anchorId) ?? [];
    bucket.push(annotation);
    destination.set(anchorId, bucket);
  }

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
  function addAnnotations(
    key: string | null,
    grouped: Map<string | null, SequenceAnnotation[]>,
  ) {
    for (const annotation of grouped.get(key) ?? []) {
      flushMoves();
      const path = key === null ? [] : (paths.get(key) ?? []);
      blocks.push({
        kind: 'annotation',
        key: `annotation:${annotation.id}`,
        annotation,
        variationDepth: path.length,
        variationPath: path,
        variationPresentation: presentationForPath(path, parentheticalRoots),
      });
    }
  }
  addAnnotations(null, before);
  addAnnotations(null, after);
  for (const node of visibleScoreMoves(item.nodes)) {
    addAnnotations(node.id, before);
    bufferedMoves.push(node);
    addAnnotations(node.id, after);
  }
  flushMoves();
  return blocks;
}

/** Select one actual line, even when other variations are displayed between its moves. */
export function reviewLinePath(
  nodes: MoveNode[],
  anchorId: string,
  focusId: string,
): string[] | null {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  function pathToRoot(nodeId: string): string[] {
    const path: string[] = [];
    let current: string | null = nodeId;
    while (current !== null && byId.has(current)) {
      path.push(current);
      current = byId.get(current)!.parent_id;
    }
    return path;
  }
  const fromFocus = pathToRoot(focusId);
  const anchorIndex = fromFocus.indexOf(anchorId);
  if (anchorIndex >= 0) return fromFocus.slice(0, anchorIndex + 1).reverse();
  const fromAnchor = pathToRoot(anchorId);
  const focusIndex = fromAnchor.indexOf(focusId);
  if (focusIndex >= 0) return fromAnchor.slice(0, focusIndex + 1).reverse();
  return null;
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
    const { moveNumber, side } = reviewMoveTurn(node);

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
