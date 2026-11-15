import {
  type BoardOutcome,
  type EvaluationScore,
  outcomeLabels,
  scoreLabel,
  whiteEvaluationPercent,
} from './courseEvaluation';
import './courseEvaluationBar.css';

const terminalScores = {
  'white-wins': { percent: 100, description: '白方将杀获胜' },
  'black-wins': { percent: 0, description: '黑方将杀获胜' },
  draw: { percent: 50, description: '和棋' },
} as const;

export function CourseEvaluationBar({
  line,
  outcome,
  orientation,
}: {
  line?: EvaluationScore;
  outcome?: BoardOutcome;
  orientation: 'white' | 'black';
}) {
  const result = outcome && terminalScores[outcome];
  const whitePercent = result?.percent ?? whiteEvaluationPercent(line);
  if (whitePercent == null)
    return (
      <div
        className="course-evaluation-bar is-empty"
        role="img"
        aria-label="当前局面暂无引擎评分"
        title="当前局面暂无引擎评分"
      />
    );

  const label = outcome ? outcomeLabels[outcome] : line ? scoreLabel(line) : '';
  const percent = Math.round(whitePercent);
  const description =
    result?.description ?? `白方视角 ${label}，白方胜势 ${percent}%`;
  const favorWhite = whitePercent >= 50;
  const labelAtBottom = favorWhite === (orientation === 'white');
  return (
    <div
      className="course-evaluation-bar"
      data-orientation={orientation}
      role="meter"
      aria-label={result ? '棋局结果' : '引擎局面评分'}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-valuetext={description}
      title={description}
    >
      <div
        className="course-evaluation-white"
        style={{ height: `${whitePercent}%` }}
      />
      <span
        className="course-evaluation-score"
        data-edge={labelAtBottom ? 'bottom' : 'top'}
        data-color={favorWhite ? 'white' : 'black'}
        aria-hidden="true"
      >
        {label}
      </span>
    </div>
  );
}
