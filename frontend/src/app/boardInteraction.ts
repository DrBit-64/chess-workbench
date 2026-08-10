import { Chess, type Square } from 'chess.js';

type CustomSquareStyles = Partial<
  Record<Square, Record<string, string | number>>
>;

export const FAST_MOVE_ANIMATION_MS = 100;

const LAST_MOVE_COLOUR = 'rgba(155, 199, 0, 0.41)';
const MOVE_DESTINATION_COLOUR = 'rgba(20, 85, 30, 0.5)';

export function lichessSquareStyles(
  fen: string,
  selectedSquare?: string,
  lastMoveUci?: string | null,
): CustomSquareStyles {
  const styles: CustomSquareStyles = {};
  if (lastMoveUci && /^[a-h][1-8][a-h][1-8]/.test(lastMoveUci)) {
    styles[lastMoveUci.slice(0, 2) as Square] = {
      backgroundColor: LAST_MOVE_COLOUR,
    };
    styles[lastMoveUci.slice(2, 4) as Square] = {
      backgroundColor: LAST_MOVE_COLOUR,
    };
  }
  if (!selectedSquare) return styles;

  try {
    const game = new Chess(fen);
    const source = selectedSquare as Square;
    const piece = game.get(source);
    if (!piece || piece.color !== game.turn()) return styles;

    styles[source] = { backgroundColor: MOVE_DESTINATION_COLOUR };
    for (const move of game.moves({ square: source, verbose: true })) {
      styles[move.to] = {
        background: move.captured
          ? `radial-gradient(transparent 0%, transparent 79%, ${MOVE_DESTINATION_COLOUR} 80%)`
          : `radial-gradient(${MOVE_DESTINATION_COLOUR} 22%, transparent 23%)`,
        cursor: 'pointer',
      };
    }
  } catch {
    // Persisted FEN is backend-validated; returning only the last-move marker is
    // the safest visual fallback if a corrupt legacy value reaches the board.
  }
  return styles;
}
