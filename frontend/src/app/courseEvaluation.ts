import type { AnalysisLine } from '../logic/api/engineTypes';

function wdlShare(line: AnalysisLine): number | undefined {
  if (!line.wdl) return;
  const [wins, draws, losses] = line.wdl;
  const total = wins + draws + losses;
  if (total > 0) return (wins + draws / 2) / total;
}

// White's point of view. The course arrows use the same Lichess scale as the bar.
export function winningChances(line: AnalysisLine): number {
  const score =
    line.mate == null ? line.score_cp : 1000 * (line.mate > 0 ? 1 : -1);
  if (score == null) return 2 * (wdlShare(line) ?? 0.5) - 1;
  const boundedScore = Math.min(1000, Math.max(-1000, score));
  return 2 / (1 + Math.exp(-0.00368208 * boundedScore)) - 1;
}

export function whiteEvaluationPercent(
  line?: AnalysisLine,
): number | undefined {
  if (!line) return;
  if (line.mate != null) return line.mate > 0 ? 100 : 0;
  if (line.score_cp != null) return 50 * (1 + winningChances(line));
  const share = wdlShare(line);
  if (share != null) return 100 * share;
}

export function scoreLabel(line: AnalysisLine): string {
  if (line.mate != null) return `#${line.mate}`;
  if (line.score_cp != null) {
    const pawns = line.score_cp / 100;
    return `${pawns >= 0 ? '+' : ''}${pawns.toFixed(2)}`;
  }
  const share = wdlShare(line);
  if (share === 1) return '白胜';
  if (share === 0) return '黑胜';
  if (share === 0.5 && line.wdl?.[0] === 0) return '和棋';
  return share != null ? `${Math.round(100 * share)}%` : '—';
}
