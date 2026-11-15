import { Switch } from 'antd';
import { useState, type ReactNode } from 'react';

import { EngineSettingsDrawer } from './EngineSettingsDrawer';
import {
  outcomeLabels,
  scoreLabel,
  type EvaluationScore,
} from './courseEvaluation';
import type { PositionEngine } from './usePositionEngine';
import './scoreEnginePanel.css';

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

export function ScoreEnginePanel({
  context,
  live,
  currentLine,
  scoreSource,
  actions,
  progress,
  onRetryScores,
  reserveLines = false,
}: {
  context: '课程' | '复盘';
  live: PositionEngine;
  currentLine?: EvaluationScore;
  scoreSource?: string;
  actions: ReactNode;
  progress?: ReactNode;
  onRetryScores?: () => void;
  reserveLines?: boolean;
}) {
  const [settings, setSettings] = useState(false);
  const [folded, setFolded] = useState(false);
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
    <section
      className="score-engine"
      aria-label={context === '课程' ? '课程实时引擎' : '棋谱引擎分析'}
    >
      <div className="score-engine-head">
        <div className="score-engine-identity">
          <Switch
            size="small"
            checked={live.enabled}
            onChange={live.setEnabled}
            aria-label={context + '实时引擎分析'}
          />
          <strong title="当前局面评分（白方视角）">{score}</strong>
          <span>
            {engineName}
            {evaluated?.depth != null && ` · 深度 ${evaluated.depth}`}
          </span>
        </div>
        <div className="score-engine-actions">
          {actions}
          <button
            type="button"
            aria-label={context + '引擎设置'}
            onClick={() => setSettings(true)}
          >
            设置
          </button>
          {live.enabled && (
            <button
              type="button"
              className="score-engine-fold"
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
      {progress}
      {live.enabled &&
        !folded &&
        (evaluated?.lines.length ? (
          <div
            key={evaluated.id}
            className="score-pvs"
            aria-label="引擎候选变化"
          >
            {evaluated.lines.map((line) => (
              <details key={line.rank}>
                <summary aria-label={`候选变化 ${line.rank}`}>
                  <span className="score-pv-score">{scoreLabel(line)}</span>
                  <span className="score-pv-moves">
                    {formatPrincipalVariation(evaluated.fen, line.san)}
                  </span>
                  <span className="score-pv-marker" aria-hidden="true">
                    ▾
                  </span>
                </summary>
              </details>
            ))}
            {reserveLines &&
              Array.from(
                {
                  length: Math.max(
                    0,
                    live.parameters.multipv - evaluated.lines.length,
                  ),
                },
                (_, index) => (
                  <div
                    className="score-pv-empty"
                    key={'empty-' + index}
                    aria-label={`线路 ${evaluated.lines.length + index + 1} 没有更多合法候选着`}
                  />
                ),
              )}
          </div>
        ) : (
          !live.outcome && (
            <p className="score-engine-hint">
              {live.analysisError ??
                (live.analyzing ? '正在计算当前局面…' : '正在连接引擎…')}
              {live.analysisError && (
                <button
                  className="score-engine-retry"
                  type="button"
                  onClick={live.retry}
                >
                  重试
                </button>
              )}
            </p>
          )
        ))}
      {onRetryScores && (
        <p className="score-engine-hint">
          暂时无法读取已存的棋步评分。
          <button
            type="button"
            className="score-engine-retry"
            onClick={onRetryScores}
          >
            重新读取
          </button>
        </p>
      )}
      {settings && (
        <EngineSettingsDrawer
          context={context}
          engine={live}
          open={settings}
          onClose={() => setSettings(false)}
        />
      )}
    </section>
  );
}
