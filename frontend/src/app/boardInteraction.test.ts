import { describe, expect, it } from 'vitest';

import {
  FAST_MOVE_ANIMATION_MS,
  lichessSquareStyles,
} from './boardInteraction';

const startFen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

describe('Lichess-style board interaction', () => {
  it('uses the fast movement duration and marks every legal destination', () => {
    const styles = lichessSquareStyles(startFen, 'e2');

    expect(FAST_MOVE_ANIMATION_MS).toBe(100);
    expect(styles.e2?.backgroundColor).toBe('rgba(20, 85, 30, 0.5)');
    expect(styles.e3?.background).toContain('radial-gradient');
    expect(styles.e4?.background).toContain('radial-gradient');
    expect(styles.e5).toBeUndefined();
  });

  it('uses a ring for captures and retains the previous move highlight', () => {
    const fen = '4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1';
    const styles = lichessSquareStyles(fen, 'e4', 'd7d5');

    expect(styles.d7?.backgroundColor).toBe('rgba(155, 199, 0, 0.41)');
    expect(styles.d5?.background).toContain('transparent 79%');
    expect(styles.e5?.background).not.toContain('transparent 79%');
  });

  it('does not expose destinations for the side that is not to move', () => {
    const styles = lichessSquareStyles(startFen, 'e7');

    expect(styles.e7).toBeUndefined();
    expect(styles.e6).toBeUndefined();
  });
});
