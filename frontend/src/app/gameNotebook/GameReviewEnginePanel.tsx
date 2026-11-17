import { RecordMovesButton } from '../../components/RecordMovesButton';
import { ScoreEnginePanel } from '../ScoreEnginePanel';
import type { useGameReviewEngine } from './useGameReviewEngine';

export function GameReviewEnginePanel({
  analysis,
  recording,
  onRecordingChange,
  editingBusy = false,
}: {
  recording?: boolean;
  onRecordingChange?: (on: boolean) => void;
  editingBusy?: boolean;
  analysis: ReturnType<typeof useGameReviewEngine>;
}) {
  const {
    live,
    currentLine,
    scoreSource,
    batch,
    analyzeGame,
    pause,
    cacheError,
  } = analysis;
  const running = batch?.status === 'checking' || batch?.status === 'running';
  return (
    <ScoreEnginePanel
      context="复盘"
      live={live}
      currentLine={currentLine}
      scoreSource={scoreSource}
      onRetryScores={cacheError && !batch ? analysis.reloadScores : undefined}
      actions={
        <>
          {onRecordingChange && (
            <RecordMovesButton
              recording={Boolean(recording)}
              disabled={editingBusy}
              onChange={onRecordingChange}
            />
          )}

          <button
            type="button"
            onClick={running ? pause : () => void analyzeGame()}
            aria-label={running ? '暂停整盘分析' : '分析整盘棋谱'}
          >
            {running ? '暂停分析' : '分析整盘'}
          </button>
        </>
      }
      progress={
        batch && (
          <p className="score-engine-progress" role="status">
            {batch.status === 'checking'
              ? '检查已存分析…'
              : batch.status === 'paused'
                ? '已暂停'
                : batch.status === 'complete'
                  ? '整盘分析已完成'
                  : batch.status === 'error'
                    ? `分析中断，可重试。${batch.message ?? ''}`
                    : '分析主线'}
            {batch.status !== 'checking' &&
              ` · ${batch.done} / ${batch.total} 个局面`}
          </p>
        )
      }
    />
  );
}
