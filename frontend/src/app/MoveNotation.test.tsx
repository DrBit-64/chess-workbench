import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MoveNotation } from './MoveNotation';
import { formatMoveNotation, moveNotationText } from './moveNotation';

describe('shared score notation', () => {
  it('normalizes capture and castling, prefers stored NAGs, and renders Lichess glyphs', () => {
    expect(moveNotationText('dXc4?!')).toBe('dxc4?!');
    expect(moveNotationText('0-0+?')).toBe('O-O+?');
    expect(moveNotationText('d×c4?!', [1])).toBe('dxc4!');
    expect(
      formatMoveNotation('Nf3', [7, 10, 14, 132, 140, 146]).annotations.map(
        ({ symbol }) => symbol,
      ),
    ).toEqual(['□', '=', '⩲', '⇆', '∆', 'N']);

    render(<MoveNotation san="dXc4?!" nags={[6]} />);
    expect(screen.getByText('dxc4')).toBeTruthy();
    expect(screen.getByTitle('可疑着法').className).toContain('text-amber-700');
    expect(screen.getAllByText('?!')).toHaveLength(1);
  });
});
