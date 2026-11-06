import type { AnalysisLine } from '../logic/api/engineTypes';
import { scoreLabel, whiteEvaluationPercent } from './courseEvaluation';
import './courseEvaluationBar.css';

export function CourseEvaluationBar({
  line,
  orientation,
}: {
  line?: AnalysisLine;
  orientation: 'white' | 'black';
}) {
  const whitePercent = whiteEvaluationPercent(line);
  if (whitePercent == null || !line)
    return (
      <div
        className="course-evaluation-bar is-empty"
        role="img"
        aria-label="当前局面暂无引擎评分"
        title="当前局面暂无引擎评分"
      />
    );

  const label = scoreLabel(line);
  const percent = Math.round(whitePercent);
  const description = `白方视角 ${label}，白方胜势 ${percent}%`;
  const favorWhite = whitePercent >= 50;
  const labelAtBottom = favorWhite === (orientation === 'white');
  return (
    <div
      className="course-evaluation-bar"
      data-orientation={orientation}
      role="meter"
      aria-label="引擎局面评分"
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
