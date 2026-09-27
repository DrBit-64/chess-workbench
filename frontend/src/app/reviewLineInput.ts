import { Chess } from 'chess.js';

export type ParsedReviewLine =
  | {
      ok: true;
      uci: string[];
      san: string[];
      nags: (number | null)[];
      fenAfter: string;
    }
  | { ok: false; token: string; index: number; message: string };

const PUNCTUATION_NAGS: Record<string, number> = {
  '!': 1,
  '?': 2,
  '!!': 3,
  '??': 4,
  '!?': 5,
  '?!': 6,
};

const PIECES: Record<string, string> = {
  '♔': 'K',
  '♚': 'K',
  '♕': 'Q',
  '♛': 'Q',
  '♖': 'R',
  '♜': 'R',
  '♗': 'B',
  '♝': 'B',
  '♘': 'N',
  '♞': 'N',
  '♙': '',
  '♟': '',
};

/** Parse notation against the chosen position; the server validates again on save. */
export function parseReviewLine(text: string, fen: string): ParsedReviewLine {
  let game: Chess;
  try {
    game = new Chess(fen);
  } catch {
    return { ok: false, token: '', index: 0, message: '起点局面无效' };
  }
  const normalized = text
    .replace(/[♔♚♕♛♖♜♗♝♘♞♙♟]/g, (piece) => PIECES[piece] ?? piece)
    .replace(
      /(\d+)\s*(\.{1,3}|…)/g,
      (_match, number: string, dots: string) =>
        ` __turn_${number}_${dots === '.' ? 'w' : 'b'}__ `,
    );
  const tokens = normalized
    .split(/[\s,;]+/)
    .map((token) => token.replace(/^[([{]+|[)\]}]+$/g, ''))
    .filter(Boolean);
  const uci: string[] = [];
  const san: string[] = [];
  const nags: (number | null)[] = [];
  for (const token of tokens) {
    const printedTurn = /^__turn_(\d+)_([wb])__$/.exec(token);
    if (printedTurn) {
      const [, side, , , , fullmove] = game.fen().split(' ');
      if (side !== printedTurn[2] || fullmove !== printedTurn[1]) {
        return {
          ok: false,
          token,
          index: uci.length,
          message: `来源步号 ${printedTurn[1]}${printedTurn[2] === 'w' ? '.' : '...'} 与所选局面不符，请检查挂接点`,
        };
      }
      continue;
    }
    const punctuation = /([!?]{1,2})$/.exec(token)?.[1];
    const cleaned = token
      .replace(/[!?]+$/g, '')
      .replace(/X/g, 'x')
      .replace(/^0-0/, 'O-O');
    try {
      const move = game.move(cleaned);
      uci.push(`${move.from}${move.to}${move.promotion ?? ''}`);
      san.push(move.san);
      nags.push(punctuation ? (PUNCTUATION_NAGS[punctuation] ?? null) : null);
    } catch {
      return {
        ok: false,
        token,
        index: uci.length,
        message: `第 ${uci.length + 1} 步 ${token} 无法从此局面走出，请检查挂接点或棋步文字`,
      };
    }
  }
  return { ok: true, uci, san, nags, fenAfter: game.fen() };
}
