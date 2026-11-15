import { useEffect, useRef, useState } from 'react';

import { ApiError } from '../logic/api/client';
import type { EngineParameters } from '../logic/api/engineTypes';
import {
  analyzePosition,
  readEngineCapabilities,
  readPositionEvaluations,
} from '../logic/api/engineAnalysis';
import { loadChapterFens } from './chapterEnginePositions';
import type { useScoreEvaluations } from './useScoreEvaluations';

type CourseSectionAnalysisProgress = {
  sectionTitle: string;
  completed: number;
  failed: number;
  total: number;
  running: boolean;
  checking: boolean;
  cached: number;
  error?: string;
};

function chapterAnalysisStatus(progress: CourseSectionAnalysisProgress) {
  const {
    sectionTitle,
    completed,
    total,
    cached,
    failed,
    error,
    checking,
    running,
  } = progress;
  let status: string;
  if (checking) status = '正在检查章节和缓存…';
  else if (error) status = error;
  else if (running) status = `正在分析 ${completed} / ${total}`;
  else if (failed) status = `${failed} 个局面失败，可再次分析补齐`;
  else if (!total)
    status = cached ? `全部 ${cached} 个局面已有缓存` : '没有可分析的局面';
  else
    status = `已保存 ${completed + cached} 个局面的评分${cached ? `（其中 ${cached} 个已有缓存）` : ''}`;
  return `${sectionTitle} · ${status}`;
}

export function useChapterAnalysis(
  courseId: string,
  section: { title: string } | undefined,
  activeFens: string[],
  descendantIds: string[],
  parameters: EngineParameters,
  evaluations: Pick<
    ReturnType<typeof useScoreEvaluations>,
    'rememberAnalysis' | 'rememberScores'
  >,
) {
  const controllerRef = useRef<AbortController>();
  const [progress, setProgress] = useState<CourseSectionAnalysisProgress>();
  const canAnalyze = Boolean(
    section && (activeFens.length || descendantIds.length),
  );

  useEffect(
    () => () => {
      controllerRef.current?.abort();
    },
    [],
  );

  async function start() {
    if (!section || !canAnalyze || controllerRef.current) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    const progress: CourseSectionAnalysisProgress = {
      sectionTitle: section.title,
      completed: 0,
      failed: 0,
      total: 0,
      cached: 0,
      running: true,
      checking: true,
    };
    function showProgress() {
      if (!controller.signal.aborted) setProgress({ ...progress });
    }
    showProgress();

    const signal = controller.signal;
    const unavailable = '电脑端引擎不可用，请检查 Stockfish 后重试';
    try {
      const fens = await loadChapterFens(
        courseId,
        activeFens,
        descendantIds,
        signal,
      );
      const { missing, scores } = await readPositionEvaluations(
        fens,
        parameters,
        signal,
      );
      if (signal.aborted) return;
      evaluations.rememberScores(scores);
      progress.cached = fens.length - missing.length;
      progress.total = missing.length;
      if (!missing.length) return;

      // Check on each explicit run, including retries after an engine was installed.
      const capabilities = await readEngineCapabilities(signal);
      if (!capabilities.available && !capabilities.syzygy_available) {
        progress.error = unavailable;
        return;
      }
      progress.checking = false;
      showProgress();

      for (const fen of missing) {
        if (signal.aborted) return;
        try {
          const analysis = await analyzePosition(fen, parameters, signal);
          if (signal.aborted) return;
          evaluations.rememberAnalysis(analysis);
        } catch (error) {
          if (signal.aborted) return;
          if (
            error instanceof ApiError &&
            error.status === 503 &&
            !capabilities.syzygy_available
          ) {
            progress.error = unavailable;
            return;
          }
          if (error instanceof TypeError) {
            progress.error = '已与工作台断开连接，请重新连接后重试';
            return;
          }
          progress.failed += 1;
        }
        progress.completed += 1;
        showProgress();
      }
    } catch {
      progress.error = '无法读取章节、缓存或引擎状态，请重试';
    } finally {
      progress.running = false;
      progress.checking = false;
      showProgress();
      controllerRef.current = undefined;
    }
  }

  return {
    start,
    running: progress?.running ?? false,
    status: progress && chapterAnalysisStatus(progress),
    canAnalyze,
  };
}
