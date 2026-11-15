import {
  boardOutcome,
  outcomeLabels,
  type EvaluationScore,
} from './courseEvaluation';

type ScorePosition = {
  id: string;
  fen: string;
  comment?: unknown;
  analyze: boolean;
  hasContinuation: boolean;
};

// A PGN [%eval] belongs to the position after the annotated move; [%eval x,d] includes depth.
function pgnEvaluation(comment: unknown): EvaluationScore | undefined {
  if (typeof comment !== 'string') return;
  const match =
    /\[%eval\s+(#?)([+-]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s*,\s*\d+)?\s*\]/i.exec(
      comment,
    );
  if (!match) return;
  const value = Number(match[2]);
  if (!Number.isFinite(value)) return;
  if (match[1]) {
    // #0 does not indicate a winner. boardOutcome handles the actual mate.
    if (!Number.isInteger(value) || value === 0) return;
    return { mate: value, score_cp: null, wdl: null };
  }
  return { score_cp: Math.round(value * 100), mate: null, wdl: null };
}

export function indexScorePositions(positions: ScorePosition[]) {
  const terminal = new Map<string, string>();
  const imported = new Map<string, EvaluationScore>();
  const fens = new Set<string>();
  for (const position of positions) {
    const { id, fen } = position;
    const annotation = pgnEvaluation(position.comment);
    if (annotation) imported.set(id, annotation);
    if (!position.analyze) continue;
    // A legal continuation rules out mate and stalemate. Material and the
    // 75-move rule can still establish an automatic draw.
    const [pieces, , , , halfmoves] = fen.split(' ');
    const outcome =
      !position.hasContinuation ||
      !/[prq]/i.test(pieces) ||
      Number(halfmoves) >= 150
        ? boardOutcome(fen)
        : undefined;
    if (outcome) terminal.set(id, outcomeLabels[outcome]);
    else fens.add(fen);
  }
  return { positions, fens: [...fens], terminal, imported };
}
