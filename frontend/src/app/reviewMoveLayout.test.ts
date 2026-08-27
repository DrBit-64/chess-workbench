import { describe, expect, it } from 'vitest';

import {
  buildReviewMoveRows,
  buildReviewReadingFlow,
  compactReviewBlocks,
} from './reviewMoveLayout';
import type { AnnotatedMoveSequenceItem, MoveNode } from './reviewMoveLayout';

function node(overrides: Partial<MoveNode> & { id: string }): MoveNode {
  return {
    parent_id: null,
    sibling_order: 0,
    move_text: 'x',
    san_candidate: null,
    uci_candidate: null,
    fen_before: null,
    fen_after: null,
    side_to_move: null,
    move_number: null,
    nags: [],
    validation_status: 'valid',
    evidence: [],
    confidence: null,
    ...overrides,
  };
}

function white(id: string, moveNumber: number, extra: Partial<MoveNode> = {}) {
  return node({ id, side_to_move: 'w', move_number: moveNumber, ...extra });
}

function black(id: string, moveNumber: number, extra: Partial<MoveNode> = {}) {
  return node({ id, side_to_move: 'b', move_number: moveNumber, ...extra });
}

function evidence(page: number) {
  return [
    {
      page,
      bbox: null,
      start_offset: null,
      end_offset: null,
      fragment_sha256: null,
    },
  ];
}

function flatten(rows: ReturnType<typeof buildReviewMoveRows>): MoveNode[] {
  return rows
    .flatMap((row) => [row.white, row.black, row.fallback])
    .filter((candidate): candidate is MoveNode => candidate !== null);
}

describe('buildReviewMoveRows', () => {
  it('projects a 12-ply linear line into 6 unindented paired rows and conserves every node', () => {
    const nodes: MoveNode[] = [];
    for (let fullmove = 1; fullmove <= 6; fullmove += 1) {
      const w = white(`w${fullmove}`, fullmove, {
        parent_id: fullmove === 1 ? null : `b${fullmove - 1}`,
        move_text: `W${fullmove}`,
        evidence: evidence(319),
      });
      const b = black(`b${fullmove}`, fullmove, {
        parent_id: w.id,
        move_text: `B${fullmove}`,
        evidence: evidence(319),
      });
      nodes.push(w, b);
    }

    const rows = buildReviewMoveRows(nodes);
    expect(rows).toHaveLength(6);
    expect(rows.length).toBeLessThan(nodes.length); // never one node per row
    for (const row of rows) {
      expect(row.variationDepth).toBe(0);
      expect(row.moveNumber).not.toBeNull();
      expect(row.white).not.toBeNull();
      expect(row.black).not.toBeNull();
      expect(row.fallback).toBeNull();
      expect(row.evidencePages).toEqual([319]); // same-page pair -> one page
    }
    expect(rows.map((row) => row.key)).toEqual([
      'w1+b1',
      'w2+b2',
      'w3+b3',
      'w4+b4',
      'w5+b5',
      'w6+b6',
    ]);

    // Conservation oracle: visual order reproduces the input by identity.
    const flattened = flatten(rows);
    expect(flattened).toHaveLength(nodes.length);
    nodes.forEach((nodeEntry, index) =>
      expect(flattened[index]).toBe(nodeEntry),
    );
  });

  it('shows both evidence pages of a two-page pair once in first-seen order', () => {
    const w = white('w1', 1, { evidence: evidence(319) });
    const b = black('b1', 1, { parent_id: 'w1', evidence: evidence(320) });
    const rows = buildReviewMoveRows([w, b]);
    expect(rows).toHaveLength(1);
    expect(rows[0].evidencePages).toEqual([319, 320]);
    expect(rows[0].white).toBe(w);
    expect(rows[0].black).toBe(b);
  });

  it('renders an alternative black move as a depth-1 black-only row without deepening descendants', () => {
    const e4 = white('e4', 1, { parent_id: null, move_text: 'e4' });
    const e5 = black('e5', 1, { parent_id: 'e4', move_text: 'e5' });
    const c5 = black('c5', 1, {
      parent_id: 'e4',
      sibling_order: 1,
      move_text: 'c5',
    });
    const d4 = white('d4', 2, { parent_id: 'c5', move_text: 'd4' });
    const g6 = black('g6', 2, {
      parent_id: 'd4',
      sibling_order: 1,
      move_text: 'g6',
    });

    const rows = buildReviewMoveRows([e4, e5, c5, d4, g6]);
    expect(rows).toHaveLength(4);

    expect(rows[0].white).toBe(e4);
    expect(rows[0].black).toBe(e5);
    expect(rows[0].variationDepth).toBe(0);

    expect(rows[1].white).toBeNull();
    expect(rows[1].black).toBe(c5);
    expect(rows[1].variationDepth).toBe(1);
    expect(rows[1].variationPath).toEqual(['c5']);

    // Primary descendant of the alternative keeps depth 1 (does not deepen).
    expect(rows[2].white).toBe(d4);
    expect(rows[2].black).toBeNull();
    expect(rows[2].variationDepth).toBe(1);
    expect(rows[2].variationPath).toEqual(['c5']);

    // Nested alternative adds one more level.
    expect(rows[3].white).toBeNull();
    expect(rows[3].black).toBe(g6);
    expect(rows[3].variationDepth).toBe(2);
    expect(rows[3].variationPath).toEqual(['c5', 'g6']);

    const compact = compactReviewBlocks(
      rows.map((row) => ({
        kind: 'move_row' as const,
        key: `move:${row.key}`,
        row,
      })),
    );
    expect(compact.map((block) => block.kind)).toEqual([
      'mainline_row',
      'variation_line',
      'variation_line',
    ]);
    expect(compact[1].kind).toBe('variation_line');
    if (compact[1].kind === 'variation_line') {
      expect(compact[1].rows.map((row) => row.key)).toEqual(['c5', 'd4']);
    }
    expect(compact[2].kind).toBe('variation_line');
    if (compact[2].kind === 'variation_line') {
      expect(compact[2].variationPath).toEqual(['c5', 'g6']);
    }
  });

  it('never pairs incompatible or nonconsecutive nodes and keeps fallback rows visible', () => {
    // Two consecutive white moves never pair.
    const w1 = white('w1', 1);
    const w2 = white('w2', 2);
    const rowsA = buildReviewMoveRows([w1, w2]);
    expect(rowsA).toHaveLength(2);
    expect(rowsA[0].white).toBe(w1);
    expect(rowsA[0].black).toBeNull();
    expect(rowsA[1].white).toBe(w2);
    expect(rowsA[1].black).toBeNull();

    // White then black with a different move number never pairs.
    const w3 = white('w3', 1);
    const b3 = black('b3', 2, { parent_id: 'w3' });
    const rowsB = buildReviewMoveRows([w3, b3]);
    expect(rowsB).toHaveLength(2);
    expect(rowsB[0].white).toBe(w3);
    expect(rowsB[1].black).toBe(b3);
    expect(rowsB[1].white).toBeNull();

    // Same move number but a different parent never pairs.
    const w4 = white('w4', 1);
    const b4 = black('b4', 1, { parent_id: 'other' });
    const rowsC = buildReviewMoveRows([w4, b4]);
    expect(rowsC).toHaveLength(2);
    expect(rowsC[1].black).toBe(b4);

    // Same move number/parent but sibling_order > 0 never pairs.
    const w5 = white('w5', 1);
    const b5 = black('b5', 1, { parent_id: 'w5', sibling_order: 1 });
    const rowsD = buildReviewMoveRows([w5, b5]);
    expect(rowsD).toHaveLength(2);
    expect(rowsD[1].black).toBe(b5);

    // Null side/move number survives as a full-width fallback row.
    const bad = node({ id: 'bad' });
    const rowsE = buildReviewMoveRows([bad]);
    expect(rowsE).toHaveLength(1);
    expect(rowsE[0].fallback).toBe(bad);
    expect(rowsE[0].white).toBeNull();
    expect(rowsE[0].black).toBeNull();
    expect(rowsE[0].moveNumber).toBeNull();

    // The input array and its nodes are never mutated.
    const input = [w1, w2, bad];
    const before = input.map((entry) => entry.id);
    buildReviewMoveRows(input);
    expect(input.map((entry) => entry.id)).toEqual(before);
    expect(input[0]).toBe(w1);
    expect(input[1]).toBe(w2);
    expect(input[2]).toBe(bad);
  });

  it('keeps later fullmoves of a long primary line unindented', () => {
    const nodes: MoveNode[] = [];
    for (let fullmove = 1; fullmove <= 10; fullmove += 1) {
      const w = white(`w${fullmove}`, fullmove, {
        parent_id: fullmove === 1 ? null : `b${fullmove - 1}`,
      });
      const b = black(`b${fullmove}`, fullmove, { parent_id: w.id });
      nodes.push(w, b);
    }
    const rows = buildReviewMoveRows(nodes);
    expect(rows).toHaveLength(10);
    expect(rows.every((row) => row.variationDepth === 0)).toBe(true);
    expect(flatten(rows).map((entry) => entry.id)).toEqual(
      nodes.map((entry) => entry.id),
    );
  });
});

describe('buildReviewReadingFlow', () => {
  it('interleaves atomic notes and true local branches without changing topology', () => {
    const n10 = black('n10', 5, { parent_id: null, move_text: 'Nc6' });
    const n11 = white('n11', 6, { parent_id: 'n10', move_text: 'Be3' });
    const n12 = white('n12', 6, {
      parent_id: 'n10',
      sibling_order: 1,
      move_text: 'O-O',
    });
    const n13 = black('n13', 6, {
      parent_id: 'n12',
      move_text: 'O-O-O',
    });
    const n30 = black('n30', 6, {
      parent_id: 'n11',
      move_text: 'O-O-O',
    });
    const item: AnnotatedMoveSequenceItem = {
      id: 'seq1',
      kind: 'move_sequence',
      title: 'Synthetic annotated score',
      initial_position: { kind: 'startpos' },
      nodes: [n10, n11, n12, n13, n30],
      annotations: [
        {
          id: 'a1',
          text: 'The local alternative begins here.',
          text_format: 'plain',
          anchor: { kind: 'move_node', node_id: 'n10', relation: 'after' },
          evidence: evidence(321),
          confidence: 0.9,
        },
        {
          id: 'a2',
          text: 'The main line resumes after this note.',
          text_format: 'plain',
          anchor: { kind: 'move_node', node_id: 'n12', relation: 'after' },
          evidence: evidence(321),
          confidence: 0.9,
        },
      ],
      reading_flow: [
        { kind: 'move', node_id: 'n10' },
        { kind: 'move', node_id: 'n11' },
        { kind: 'annotation', annotation_id: 'a1' },
        { kind: 'move', node_id: 'n12' },
        { kind: 'move', node_id: 'n13' },
        { kind: 'annotation', annotation_id: 'a2' },
        { kind: 'move', node_id: 'n30' },
      ],
      evidence: evidence(321),
      confidence: 0.9,
    };

    const blocks = buildReviewReadingFlow(item);
    expect(blocks.map((block) => block.kind)).toEqual([
      'move_row',
      'move_row',
      'annotation',
      'move_row',
      'annotation',
      'move_row',
    ]);
    expect(
      blocks.map((block) =>
        block.kind === 'annotation'
          ? block.annotation.id
          : [block.row.white?.id, block.row.black?.id]
              .filter(Boolean)
              .join('+'),
      ),
    ).toEqual(['n10', 'n11', 'a1', 'n12+n13', 'a2', 'n30']);

    const variation = blocks[3];
    expect(variation.kind).toBe('move_row');
    if (variation.kind === 'move_row') {
      expect(variation.row.variationDepth).toBe(1);
    }
    const resumedMainline = blocks[5];
    expect(resumedMainline.kind).toBe('move_row');
    if (resumedMainline.kind === 'move_row') {
      expect(resumedMainline.row.variationDepth).toBe(0);
      expect(resumedMainline.row.black).toBe(n30);
    }

    // Presentation never rewrites the actual branch parents.
    expect(n11.parent_id).toBe('n10');
    expect(n12.parent_id).toBe('n10');
    expect(n13.parent_id).toBe('n12');
    expect(n30.parent_id).toBe('n11');
  });
});
