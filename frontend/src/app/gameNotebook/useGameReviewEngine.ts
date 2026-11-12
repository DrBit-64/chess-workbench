import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import useSWR from 'swr';

import { requestJson } from '../../logic/api/client';
import type {
  Analysis,
  AnalysisCacheLookup,
  EngineCapabilities,
  EngineParameters,
} from '../../logic/api/engineTypes';
import { boardOutcome, type BoardOutcome } from '../chapterEnginePositions';
import { scoreLabel, type EvaluationScore } from '../courseEvaluation';
import { useCourseEngine } from '../useCourseEngine';
import { indexReviewTree } from './reviewTree';
import type { ReviewGame, ReviewNode } from './reviewTypes';

type ScoresByFen = Map<string, EvaluationScore>;
export const outcomeLabels: Record<BoardOutcome, string> = {
  'white-wins': '1–0',
  'black-wins': '0–1',
  draw: '½–½',
};

// A PGN [%eval] belongs to the position after the annotated move; [%eval x,d] includes depth.
export function pgnEvaluation(comment: string): EvaluationScore | undefined {
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

async function readGameScores(
  fens: string[],
  parameters: EngineParameters,
  signal?: AbortSignal,
) {
  const scores: ScoresByFen = new Map();
  const missing: string[] = [];
  for (let i = 0; i < fens.length; i += 500) {
    const response = await requestJson<AnalysisCacheLookup>(
      '/api/engine/analyses/cache-lookup',
      {
        method: 'POST',
        signal,
        body: JSON.stringify({
          fens: fens.slice(i, i + 500),
          parameters,
          include_scores: true,
        }),
      },
    );
    for (const score of response.cached_scores ?? [])
      scores.set(score.fen, score);
    missing.push(...response.missing_fens);
  }
  return { scores, missing };
}

type BatchState = {
  scope: string;
  status: 'checking' | 'running' | 'paused' | 'complete' | 'error';
  done: number;
  total: number;
  message?: string;
};

export function reviewAnalysisPositions(nodes: ReviewNode[]) {
  const { root, children } = indexReviewTree(nodes);
  const preferred = new Set<string>();
  for (let move = root; move; move = children.get(move.id)?.[0])
    preferred.add(move.id);
  const terminal = new Map<string, string>();
  const fens = new Set<string>();
  const imported = new Map<string, EvaluationScore>();
  const hasContinuation = new Set(nodes.map((n) => n.parent_id));
  for (const n of nodes) {
    const annotation = pgnEvaluation(n.comment);
    if (annotation) imported.set(n.id, annotation);
    if (n.hidden || (!n.is_mainline && !preferred.has(n.id))) continue;
    // A recorded legal continuation excludes mate/stalemate, even if that move was hidden.
    const outcome =
      !hasContinuation.has(n.id) ||
      !/[prq]/i.test(n.fen.split(' ')[0]) ||
      Number(n.fen.split(' ')[4]) >= 150
        ? boardOutcome(n.fen)
        : undefined;
    if (outcome) terminal.set(n.id, outcomeLabels[outcome]);
    else fens.add(n.fen);
  }
  return { fens: [...fens], terminal, imported };
}

export function useGameReviewEngine(
  game: ReviewGame,
  node?: ReviewNode,
  fen = node?.fen,
) {
  const live = useCourseEngine(fen, true);
  const { parameters } = live;
  const controller = useRef<AbortController>();
  const [batchState, setBatch] = useState<BatchState>();
  const [fresh, setFresh] = useState<{ scope: string; scores: ScoresByFen }>();
  const positions = useMemo(
    () => reviewAnalysisPositions(game.nodes),
    [game.nodes],
  );
  // A tree edit can change which positions a completed or running batch covers.
  const scope = useMemo(
    () => JSON.stringify([game.id, parameters, positions.fens]),
    [game.id, parameters, positions],
  );
  const cached = useSWR(
    ['notebook-engine-scores', scope],
    () => readGameScores(positions.fens, parameters),
    {
      // A batch may finish just before returning from a bookmark or another tab.
      // Always read persisted scores on re-entry, even within SWR's default two seconds.
      dedupingInterval: 0,
      revalidateOnFocus: true,
    },
  );

  const recordScore = useCallback(
    (fen: string, score: EvaluationScore) => {
      setFresh((old) => {
        const scores = new Map(old?.scope === scope ? old.scores : undefined);
        scores.set(fen, score);
        return { scope, scores };
      });
    },
    [scope],
  );

  // The shared hook only returns an analysis for the current FEN and settings.
  useEffect(() => {
    const line = live.analysis?.lines[0];
    if (line && live.analysis) recordScore(live.analysis.fen, line);
  }, [live.analysis, recordScore]);

  // A navigation to another game, parameter change or unmount stops future requests.
  useEffect(() => {
    setBatch(undefined);
    return () => {
      controller.current?.abort();
      controller.current = undefined;
    };
  }, [scope]);

  const localScores = useMemo(() => {
    const result = new Map(cached.data?.scores);
    if (fresh?.scope === scope)
      for (const [fen, score] of fresh.scores) result.set(fen, score);
    return result;
  }, [cached.data, fresh, scope]);
  const scores = useMemo(() => {
    const result = new Map(positions.terminal);
    for (const n of game.nodes) {
      if (n.hidden || result.has(n.id)) continue;
      const value = localScores.get(n.fen) ?? positions.imported.get(n.id);
      if (value) result.set(n.id, scoreLabel(value));
    }
    return result;
  }, [game.nodes, positions, localScores]);
  const cachedCurrent = fen ? localScores.get(fen) : undefined;
  const importedCurrent =
    node && node.fen === fen ? positions.imported.get(node.id) : undefined;
  const currentLine =
    live.analysis?.lines[0] ?? cachedCurrent ?? importedCurrent;
  const scoreSource = live.analysis
    ? live.analysis.engine_name
    : cachedCurrent
      ? '已存分析'
      : importedCurrent
        ? '原谱评分'
        : undefined;

  async function analyzeGame() {
    if (controller.current) return;
    const current = new AbortController();
    const { signal } = current;
    controller.current = current;
    const total = positions.fens.length;
    let done = 0;
    setBatch({ scope, status: 'checking', done, total });
    try {
      // Check persisted results on every retry; another device may have completed the work.
      const saved = await readGameScores(positions.fens, parameters, signal);
      if (signal.aborted) return;
      void cached.mutate(saved, { revalidate: false });
      done = total - saved.missing.length;
      if (saved.missing.length) {
        const caps = await requestJson<EngineCapabilities>(
          '/api/engine/capabilities',
          { method: 'GET', signal },
        );
        if (!caps.available && !caps.syzygy_available)
          throw Error('电脑端引擎不可用。请检查 Stockfish 后重试。');
      }
      for (const fen of saved.missing) {
        if (signal.aborted) return;
        setBatch({ scope, status: 'running', done, total });
        const analysis = await requestJson<Analysis>('/api/engine/analyses', {
          method: 'POST',
          signal,
          body: JSON.stringify({ fen, parameters }),
        });
        if (signal.aborted) return;
        if (analysis.lines[0]) recordScore(fen, analysis.lines[0]);
        done++;
      }
      if (!signal.aborted) setBatch({ scope, status: 'complete', done, total });
    } catch (error) {
      if (!signal.aborted)
        setBatch({
          scope,
          status: 'error',
          done,
          total,
          message: error instanceof Error ? error.message : '引擎分析中断。',
        });
    } finally {
      if (controller.current === current) controller.current = undefined;
    }
  }
  function pause() {
    controller.current?.abort();
    controller.current = undefined;
    setBatch((old) => old && { ...old, status: 'paused' });
  }
  return {
    live,
    scores,
    currentLine,
    scoreSource,
    batch: batchState?.scope === scope ? batchState : undefined,
    analyzeGame,
    pause,
    cacheError: Boolean(cached.error),
  };
}
