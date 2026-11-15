import { useEffect, useMemo, useRef, useState } from 'react';

import {
  analyzePosition,
  readEngineCapabilities,
  readPositionEvaluations,
} from '../../logic/api/engineAnalysis';
import { indexScorePositions } from '../scoreEvaluations';
import { useScoreEvaluations } from '../useScoreEvaluations';
import { usePositionEngine } from '../usePositionEngine';
import { indexReviewTree } from './reviewTree';
import type { ReviewGame, ReviewNode } from './reviewTypes';

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
  const parents = new Set(nodes.map((node) => node.parent_id));
  return indexScorePositions(
    nodes.map((node) => ({
      id: node.id,
      fen: node.fen,
      comment: node.comment,
      hasContinuation: parents.has(node.id),
      analyze: !node.hidden && (node.is_mainline || preferred.has(node.id)),
    })),
  );
}

export function useGameReviewEngine(
  game: ReviewGame,
  node?: ReviewNode,
  fen = node?.fen,
) {
  const live = usePositionEngine(fen, true);
  const { parameters } = live;
  const controller = useRef<AbortController>();
  const [batchState, setBatch] = useState<BatchState>();
  const positions = useMemo(
    () => reviewAnalysisPositions(game.nodes),
    [game.nodes],
  );
  // A tree edit can change which positions a completed or running batch covers.
  const scope = useMemo(
    () => JSON.stringify([game.id, parameters, positions.fens]),
    [game.id, parameters, positions],
  );
  const evaluations = useScoreEvaluations(
    positions,
    live,
    fen,
    node?.fen === fen ? node?.id : undefined,
  );

  // A navigation to another game, parameter change or unmount stops future requests.
  useEffect(() => {
    setBatch(undefined);
    return () => {
      controller.current?.abort();
      controller.current = undefined;
    };
  }, [scope]);

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
      const saved = await readPositionEvaluations(
        positions.fens,
        parameters,
        signal,
      );
      if (signal.aborted) return;
      evaluations.rememberScores(saved.scores);
      done = total - saved.missing.length;
      if (saved.missing.length) {
        const caps = await readEngineCapabilities(signal);
        if (!caps.available && !caps.syzygy_available)
          throw Error('电脑端引擎不可用。请检查 Stockfish 后重试。');
      }
      for (const fen of saved.missing) {
        if (signal.aborted) return;
        setBatch({ scope, status: 'running', done, total });
        const analysis = await analyzePosition(fen, parameters, signal);
        if (signal.aborted) return;
        evaluations.rememberAnalysis(analysis);
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
    ...evaluations,
    batch: batchState?.scope === scope ? batchState : undefined,
    analyzeGame,
    pause,
  };
}
