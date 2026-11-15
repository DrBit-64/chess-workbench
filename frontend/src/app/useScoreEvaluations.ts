import { useCallback, useEffect, useMemo, useState } from 'react';
import useSWR from 'swr';

import { readPositionEvaluations } from '../logic/api/engineAnalysis';
import type { Analysis } from '../logic/api/engineTypes';
import { scoreLabel, type EvaluationScore } from './courseEvaluation';
import type { indexScorePositions } from './scoreEvaluations';
import type { PositionEngine } from './usePositionEngine';

type Scores = ReadonlyMap<string, EvaluationScore>;

export function useScoreEvaluations(
  plan: ReturnType<typeof indexScorePositions>,
  live: PositionEngine,
  fen?: string,
  occurrenceId?: string,
) {
  const { parameters, analysis } = live;
  const saved = useSWR(
    plan.fens.length ? ['engine-position-scores', parameters, plan.fens] : null,
    () => readPositionEvaluations(plan.fens, parameters),
    { dedupingInterval: 0 },
  );
  // A chapter batch can continue after the reader switches sections or settings.
  // Its callbacks keep the original parameters; scores for identical full FENs
  // can be shared across the sections currently open in the reader.
  const settings = JSON.stringify(parameters);
  const [recent, setRecent] = useState(() => new Map<string, Scores>());
  const rememberScores = useCallback(
    (entries: Scores) => {
      if (entries.size === 0) return;
      setRecent((old) => {
        const scores = new Map(old.get(settings));
        for (const [fen, score] of entries) scores.set(fen, score);
        return new Map(old).set(settings, scores);
      });
    },
    [settings],
  );
  const rememberAnalysis = useCallback(
    (result: Analysis) => {
      const first = result.lines[0];
      if (first) rememberScores(new Map([[result.fen, first]]));
    },
    [rememberScores],
  );
  useEffect(() => {
    if (analysis) rememberAnalysis(analysis);
  }, [analysis, rememberAnalysis]);

  const byFen = useMemo(() => {
    const merged = new Map<string, EvaluationScore>(saved.data?.scores);
    for (const [fen, score] of recent.get(settings) ?? [])
      merged.set(fen, score);
    return merged;
  }, [saved.data, recent, settings]);
  const scores = useMemo(() => {
    const labels = new Map(plan.terminal);
    for (const { id, fen } of plan.positions) {
      if (labels.has(id)) continue;
      const line = byFen.get(fen) ?? plan.imported.get(id);
      if (line) labels.set(id, scoreLabel(line));
    }
    return labels;
  }, [byFen, plan]);
  const cached = fen ? byFen.get(fen) : undefined;
  const annotation = occurrenceId ? plan.imported.get(occurrenceId) : undefined;
  return {
    scores,
    currentLine: analysis?.lines[0] ?? cached ?? annotation,
    scoreSource:
      analysis?.engine_name ??
      (cached ? '已存分析' : annotation ? '原谱评分' : undefined),
    rememberScores,
    rememberAnalysis,
    cacheError: Boolean(saved.error),
    reloadScores: () => void saved.mutate().catch(() => {}),
  };
}
