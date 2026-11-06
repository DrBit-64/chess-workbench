import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ModuleEditor } from '../logic/api/types';
import { CourseScore, CourseScoreControls } from './CourseScore';

type Occurrence = ModuleEditor['occurrences'][number];

function occurrence(
  id: string,
  parentId: string | null,
  san: string | null,
  fen: string,
  comment?: string,
  sortOrder = 0,
): Occurrence {
  return {
    id,
    course_id: 'course',
    module_id: 'module',
    position_id: `position-${id}`,
    parent_id: parentId,
    inbound_move_edge_id: parentId ? `edge-${id}` : null,
    full_fen: fen,
    inbound_san: san,
    inbound_uci: san,
    nag: null,
    sort_order: sortOrder,
    context: comment ? { pgn_comment: comment } : {},
    version: 1,
    archived_at: null,
    created_at: '2026-10-03T00:00:00Z',
    updated_at: '2026-10-03T00:00:00Z',
  };
}

describe('CourseScore PGN comments', () => {
  it('shows book comments at the root, mainline moves and a variation', () => {
    const root = occurrence(
      'root',
      null,
      null,
      '8/8/8/8/8/8/8/8 w - - 0 1',
      'Book introduction',
    );
    const e4 = occurrence(
      'e4',
      'root',
      'e4',
      '8/8/8/8/4P3/8/8/8 b - - 0 1',
      'Why White advances the pawn',
    );
    const e5 = occurrence(
      'e5',
      'e4',
      'e5',
      '8/8/8/4p3/4P3/8/8/8 w - - 0 2',
      'Black challenges the centre',
    );
    const d4 = occurrence(
      'd4',
      'root',
      'd4',
      '8/8/8/8/3P4/8/8/8 b - - 0 1',
      'Alternative plan',
      1,
    );

    const { container } = render(
      <CourseScore
        occurrences={[root, e4, e5, d4]}
        notes={[]}
        rootId="root"
        sourcePageBySpanId={new Map()}
        onSelectOccurrence={vi.fn()}
        onSelectSource={vi.fn()}
        onMoveAction={vi.fn()}
      />,
    );

    for (const text of [
      'Book introduction',
      'Why White advances the pawn',
      'Black challenges the centre',
      'Alternative plan',
    ]) {
      expect(screen.getByText(text)).toBeTruthy();
    }
    const displayed = container.textContent ?? '';
    expect(displayed.indexOf('Why White advances the pawn')).toBeLessThan(
      displayed.indexOf('Black challenges the centre'),
    );
  });
});

it('returns from a nested variation to its nearest fork', () => {
  const fen = '8/8/8/8/8/8/8/8 w - - 0 1';
  const occurrences = [
    occurrence('root', null, null, fen),
    occurrence('e4', 'root', 'e4', fen),
    occurrence('d4', 'root', 'd4', fen, undefined, 1),
    occurrence('d5', 'd4', 'd5', fen),
    occurrence('Nf6', 'd4', 'Nf6', fen, undefined, 1),
    occurrence('c4', 'Nf6', 'c4', fen),
  ];
  const select = vi.fn();
  const controls = (id: string) => (
    <CourseScoreControls
      occurrences={occurrences}
      rootId="root"
      currentId={id}
      readerOnly
      onSelectOccurrence={select}
      recordMoves={false}
      onRecordMovesChange={vi.fn()}
      boardOrientation="white"
      onFlipBoard={vi.fn()}
    />
  );
  const { rerender } = render(controls('c4'));
  fireEvent.click(screen.getByRole('button', { name: '回到分岔处' }));
  expect(select).toHaveBeenLastCalledWith('d4');
  rerender(controls('d4'));
  fireEvent.click(screen.getByRole('button', { name: '回到分岔处' }));
  expect(select).toHaveBeenLastCalledWith('root');
  rerender(controls('e4'));
  expect(screen.queryByRole('button', { name: '回到分岔处' })).toBeNull();
});
