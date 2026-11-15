import { ScoreEnginePanel } from './ScoreEnginePanel';
import type { useChapterAnalysis } from './useChapterAnalysis';
import type { PositionEngine } from './usePositionEngine';
import type { useScoreEvaluations } from './useScoreEvaluations';

export function CourseEnginePanel({
  engine,
  evaluations,
  sectionPositions,
  hasDescendants,
  chapter,
}: {
  engine: PositionEngine;
  evaluations: ReturnType<typeof useScoreEvaluations>;
  sectionPositions: number;
  hasDescendants: boolean;
  chapter: ReturnType<typeof useChapterAnalysis>;
}) {
  return (
    <ScoreEnginePanel
      context="课程"
      live={engine}
      currentLine={evaluations.currentLine}
      scoreSource={evaluations.scoreSource}
      reserveLines
      onRetryScores={
        evaluations.cacheError ? evaluations.reloadScores : undefined
      }
      actions={
        <button
          type="button"
          aria-label={hasDescendants ? '分析当前章节' : '引擎分析当前小节'}
          title={
            hasDescendants
              ? '分析此章和下属小节'
              : `预计算并保存 ${sectionPositions} 个局面`
          }
          disabled={!chapter.canAnalyze || chapter.running}
          onClick={chapter.start}
        >
          {hasDescendants ? '分析当前章节' : '分析本小节'}
        </button>
      }
      progress={
        chapter.status && (
          <p className="score-engine-progress" role="status">
            {chapter.status}
          </p>
        )
      }
    />
  );
}
