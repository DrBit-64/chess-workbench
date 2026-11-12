import { Switch } from 'antd';
import { useState } from 'react';
import { EngineSettingsDrawer } from '../EngineSettingsDrawer';
import { scoreLabel } from '../courseEvaluation';
import { outcomeLabels, type useGameReviewEngine } from './useGameReviewEngine';
import './gameReviewEngine.css';

function formatPrincipalVariation(fen: string, san: string[]) {
  const fields = fen.split(' ');
  let white = fields[1] === 'w';
  let number = Number(fields[5]);
  return san
    .map((move, index) => {
      const prefix = white ? `${number}. ` : index === 0 ? `${number}... ` : '';
      if (!white) number++;
      white = !white;
      return prefix + move;
    })
    .join(' ');
}

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
  const [settings, setSettings] = useState(false);
  const [folded, setFolded] = useState(false);
  const running = batch?.status === 'checking' || batch?.status === 'running';
  const evaluated = live.analysis;
  const score = live.outcome
    ? outcomeLabels[live.outcome]
    : currentLine
      ? scoreLabel(currentLine)
      : '—';
  const engineName = live.outcome
    ? '终局'
    : (scoreSource ?? live.capabilities?.engine_name ?? '引擎');
  return (
    <section className="game-review-engine" aria-label="棋谱引擎分析">
      <div className="game-review-engine-head">
        <div className="game-review-engine-identity">
          <Switch
            size="small"
            checked={live.enabled}
            onChange={live.setEnabled}
            aria-label="复盘实时引擎分析"
          />
          <strong title="当前局面评分（白方视角）">{score}</strong>
          <span>
            {engineName}
            {evaluated?.depth != null && ` · 深度 ${evaluated.depth}`}
          </span>
        </div>
        <div className="game-review-engine-actions">
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
          <button
            type="button"
            aria-label="复盘引擎设置"
            onClick={() => setSettings(true)}
          >
            设置
          </button>
          {live.enabled && (
            <button
              type="button"
              className="game-review-engine-fold"
              aria-label={folded ? '展开候选变化' : '收起候选变化'}
              title={folded ? '展开候选变化' : '收起候选变化'}
              aria-expanded={!folded}
              onClick={() => setFolded(!folded)}
            >
              {folded ? '▾' : '▴'}
            </button>
          )}
        </div>
      </div>
      {batch && (
        <p className="game-review-engine-progress" role="status">
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
      )}
      {live.enabled &&
        !folded &&
        (evaluated?.lines.length ? (
          <div
            key={evaluated.id}
            className="game-review-pvs"
            aria-label="引擎候选变化"
          >
            {evaluated.lines.map((line) => (
              <details key={line.rank}>
                <summary aria-label={`候选变化 ${line.rank}`}>
                  <span className="game-review-pv-score">
                    {scoreLabel(line)}
                  </span>
                  <span className="game-review-pv-moves">
                    {formatPrincipalVariation(evaluated.fen, line.san)}
                  </span>
                  <span className="game-review-pv-marker" aria-hidden="true">
                    ▾
                  </span>
                </summary>
              </details>
            ))}
          </div>
        ) : (
          !live.outcome && (
            <p className="game-review-engine-hint">
              {live.capabilities &&
              !live.capabilities.available &&
              !live.capabilities.syzygy_available
                ? '电脑端 Stockfish 不可用。'
                : (live.analysisError ??
                  (live.analyzing ? '正在计算当前局面…' : '正在连接引擎…'))}
              {live.analysisError && (
                <button
                  className="game-review-engine-retry"
                  type="button"
                  onClick={live.retry}
                >
                  重试
                </button>
              )}
            </p>
          )
        ))}
      {cacheError && !batch && (
        <p className="game-review-engine-hint">
          已存的逐着评分暂时无法读取，可点击「分析整盘」重试。
        </p>
      )}
      {settings && (
        <EngineSettingsDrawer
          context="复盘"
          engine={live}
          open={settings}
          onClose={() => setSettings(false)}
        />
      )}
    </section>
  );
}
