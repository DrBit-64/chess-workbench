import { type ComponentProps, useEffect, useMemo, useState } from 'react';
import type { Chessboard } from 'react-chessboard';
import useSWR from 'swr';

import { fetchJson, requestJson } from '../logic/api/client';
import type {
  Analysis,
  EngineCapabilities,
  EngineParameters,
} from '../logic/api/engineTypes';
import { boardOutcome } from './chapterEnginePositions';
import { winningChances } from './courseEvaluation';

const DEFAULT_PARAMETERS: EngineParameters = {
  multipv: 4,
  movetime_ms: 800,
  depth: null,
  threads: 1,
  hash_mb: 128,
  ponder: false,
};

const BEST_ARROW_COLOR = 'rgba(31, 90, 165, 0.86)';
const MAX_VISIBLE_WINNING_CHANCE_LOSS = 0.2;

export type CourseEngineArrow = NonNullable<
  ComponentProps<typeof Chessboard>['customArrows']
>[number];
type BoardSquare = CourseEngineArrow[0];

function alternativeArrowColor(loss: number): string {
  const ratio = Math.min(
    1,
    Math.max(0, loss / MAX_VISIBLE_WINNING_CHANCE_LOSS),
  );
  const red = Math.round(57 + 78 * ratio);
  const green = Math.round(91 + 44 * ratio);
  const blue = Math.round(143 - 8 * ratio);
  const opacity = (0.64 - 0.38 * ratio).toFixed(2);
  return `rgba(${red}, ${green}, ${blue}, ${opacity})`;
}

type PositionResponse = {
  fen: string;
  parameters: EngineParameters;
  analysis?: Analysis;
  error?: string;
};

export function useCourseEngine(
  fen: string | undefined,
  defaultEnabled: boolean,
) {
  const [explicitlyEnabled, setEnabled] = useState<boolean>();
  const enabled = explicitlyEnabled ?? defaultEnabled;
  const [showArrows, setShowArrows] = useState(true);
  const [preferredArrowCount, setArrowCount] = useState(3);
  const [customParameters, setParameters] = useState<EngineParameters>();
  const [response, setResponse] = useState<PositionResponse>();
  const [attempt, setAttempt] = useState(0);
  const {
    data: capabilities,
    error: capabilityError,
    mutate: checkEngine,
  } = useSWR<EngineCapabilities>(
    enabled && fen ? '/api/engine/capabilities' : null,
    fetchJson,
  );
  const defaults = capabilities?.default_parameters;
  const parameters = useMemo<EngineParameters>(
    () =>
      customParameters ?? {
        ...DEFAULT_PARAMETERS,
        ...defaults,
      },
    [customParameters, defaults],
  );
  const arrowCount = Math.min(preferredArrowCount, parameters.multipv, 4);
  const outcome = useMemo(() => (fen ? boardOutcome(fen) : undefined), [fen]);
  const available = capabilities?.available || capabilities?.syzygy_available;
  const shouldAnalyze = Boolean(enabled && available && !outcome);

  useEffect(() => {
    if (!shouldAnalyze || !fen) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void requestJson<Analysis>('/api/engine/analyses', {
        method: 'POST',
        signal: controller.signal,
        body: JSON.stringify({ fen, parameters }),
      }).then(
        (analysis) => {
          if (!controller.signal.aborted)
            setResponse({ fen, parameters, analysis });
        },
        (error: unknown) => {
          if (!controller.signal.aborted)
            setResponse({
              fen,
              parameters,
              error: error instanceof Error ? error.message : '局面分析失败',
            });
        },
      );
    }, 80);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [fen, parameters, shouldAnalyze, attempt]);

  // Navigation changes the board during render, before the previous effect cleans up.
  const current =
    shouldAnalyze &&
    response?.fen === fen &&
    response?.parameters === parameters
      ? response
      : undefined;
  const analysis = current?.analysis;
  const analysisError =
    enabled && fen && !outcome
      ? capabilityError
        ? '无法读取电脑端引擎状态'
        : capabilities && !available
          ? (capabilities.install_hint ?? '请在电脑上安装 Stockfish')
          : current?.error
      : undefined;
  const analyzing = Boolean(shouldAnalyze && fen && !current);

  const arrows = useMemo<CourseEngineArrow[]>(() => {
    if (!showArrows || !analysis || !fen) return [];
    const bestLine = analysis.lines[0];
    if (!bestLine) return [];
    const sideMultiplier = fen.split(' ')[1] === 'b' ? -1 : 1;
    const bestWinningChances = winningChances(bestLine) * sideMultiplier;
    return analysis.lines
      .slice(0, Math.min(arrowCount, 4))
      .flatMap((line, index) => {
        const move = line.uci[0];
        if (!move) return [];
        const loss = Math.max(
          0,
          (bestWinningChances - winningChances(line) * sideMultiplier) / 2,
        );
        if (index > 0 && loss >= MAX_VISIBLE_WINNING_CHANCE_LOSS) return [];
        return [
          [
            move.slice(0, 2) as BoardSquare,
            move.slice(2, 4) as BoardSquare,
            index === 0 ? BEST_ARROW_COLOR : alternativeArrowColor(loss),
          ],
        ];
      });
  }, [analysis, arrowCount, fen, showArrows]);

  return {
    enabled,
    setEnabled,
    retry: () => {
      setResponse(undefined);
      setAttempt((a) => a + 1);
      void checkEngine();
    },
    capabilities,
    parameters,
    setParameters,
    showArrows,
    setShowArrows,
    arrowCount,
    setArrowCount,
    analysis,
    analysisError,
    analyzing,
    outcome,
    arrows,
  };
}
