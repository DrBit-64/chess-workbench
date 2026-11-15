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
            <button
              className="game-review-record"
              type="button"
              aria-label="记录走棋"
              aria-pressed={Boolean(recording)}
              title={recording ? '关闭记录走棋' : '开启记录走棋'}
              disabled={editingBusy}
              onClick={() => onRecordingChange(!recording)}
            >
              <svg
                aria-hidden="true"
                width="17"
                height="17"
                viewBox="0 0 20 20"
              >
                <circle
                  cx="10"
                  cy="10"
                  r="8"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                />
                <circle cx="10" cy="10" r="4.2" fill="currentColor" />
              </svg>
            </button>
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
