import { Alert, Button, Progress, Space, Spin, Switch, Typography } from 'antd';
import { useState } from 'react';

import { EngineSettingsDrawer } from './EngineSettingsDrawer';
import { scoreLabel } from './courseEvaluation';
import type { useCourseEngine } from './useCourseEngine';

export type CourseSectionAnalysisProgress = {
  sectionId: string;
  sectionTitle: string;
  completed: number;
  failed: number;
  total: number;
  running: boolean;
  checking: boolean;
  cached: number;
  error?: string;
};

export function CourseEnginePanel({
  engine,
  sectionPositions,
  hasDescendants,
  sectionProgress,
  onAnalyzeSection,
}: {
  engine: ReturnType<typeof useCourseEngine>;
  sectionPositions: number;
  hasDescendants: boolean;
  sectionProgress?: CourseSectionAnalysisProgress;
  onAnalyzeSection: () => void;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const {
    enabled,
    setEnabled,
    parameters,
    analysis,
    analysisError,
    analyzing,
    outcome,
  } = engine;

  return (
    <section className="course-engine-panel" aria-label="课程实时引擎">
      <div className="course-engine-header">
        <Space size="small">
          <Switch
            aria-label="课程实时引擎分析"
            checked={enabled}
            onChange={setEnabled}
          />
          <Typography.Text strong>引擎分析</Typography.Text>
          <Typography.Text type="secondary" className="text-xs">
            {enabled
              ? analysis
                ? `${analysis.engine_name} · 深度 ${analysis.depth ?? '—'}`
                : analyzing
                  ? '正在计算当前局面'
                  : outcome
                    ? '当前局面已结束'
                    : '等待引擎'
              : '关闭'}
          </Typography.Text>
        </Space>
        <Space size="small">
          <Button
            size="small"
            aria-label={hasDescendants ? '分析当前章节' : '引擎分析当前小节'}
            title={
              hasDescendants
                ? '分析此章和下属小节'
                : `预计算并保存 ${sectionPositions} 个局面`
            }
            disabled={
              (!sectionPositions && !hasDescendants) || sectionProgress?.running
            }
            loading={sectionProgress?.running}
            onClick={onAnalyzeSection}
          >
            {hasDescendants ? '分析当前章节' : '分析本小节'}
          </Button>
          <Button
            size="small"
            aria-label="课程引擎设置"
            onClick={() => setSettingsOpen(true)}
          >
            设置
          </Button>
        </Space>
      </div>

      {sectionProgress ? (
        <div className="course-engine-bulk">
          <div className="min-w-0 flex-1">
            <div className="mb-1 text-xs text-stone-600">
              {sectionProgress.checking
                ? '正在检查缓存'
                : sectionProgress.running
                  ? '正在分析'
                  : sectionProgress.error
                    ? '已停止'
                    : '已完成'}
              「{sectionProgress.sectionTitle}」
            </div>
            {sectionProgress.checking ? (
              <div className="course-engine-loading min-h-0 justify-start py-1">
                <Spin size="small" />
                <span>正在查找已保存的局面…</span>
              </div>
            ) : sectionProgress.total ? (
              <Progress
                aria-label="小节引擎分析进度"
                percent={Math.round(
                  (sectionProgress.completed / sectionProgress.total) * 100,
                )}
                size="small"
                status={
                  !sectionProgress.running &&
                  (sectionProgress.error || sectionProgress.failed)
                    ? 'exception'
                    : undefined
                }
                format={() =>
                  `${sectionProgress.completed} / ${sectionProgress.total}`
                }
              />
            ) : null}
            {!sectionProgress.checking && sectionProgress.cached ? (
              <div className="text-xs text-stone-600">
                已跳过 {sectionProgress.cached} 个缓存局面
              </div>
            ) : null}
            {!sectionProgress.running && !sectionProgress.checking ? (
              <div className="text-xs text-stone-600" aria-live="polite">
                {sectionProgress.error ??
                  (sectionProgress.total === 0
                    ? sectionProgress.cached
                      ? `全部 ${sectionProgress.cached} 个局面已有缓存`
                      : '没有可分析的局面'
                    : sectionProgress.failed
                      ? `${sectionProgress.failed} 个局面失败，可再次运行补齐`
                      : '本小节分析已保存')}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {enabled ? (
        <div aria-live="polite">
          {analysisError ? (
            <Alert type="error" showIcon title={analysisError} />
          ) : analyzing ? (
            <div className="course-engine-loading">
              <Spin size="small" />
              <span>分析当前局面…</span>
            </div>
          ) : analysis?.lines.length ? (
            <div className="course-pv-list" aria-label="当前局面引擎线路">
              {Array.from({ length: parameters.multipv }, (_, index) => {
                const line = analysis.lines[index];
                return (
                  <div
                    className="course-pv-row"
                    key={line?.rank ?? `empty-${index + 1}`}
                    aria-label={
                      line ? undefined : `线路 ${index + 1} 没有更多合法候选着`
                    }
                  >
                    <span className="course-pv-rank">{index + 1}</span>
                    <span className="course-pv-score">
                      {line ? scoreLabel(line) : '\u00a0'}
                    </span>
                    <span className="course-pv-moves">
                      {line ? line.san.join(' ') : '\u00a0'}
                    </span>
                  </div>
                );
              })}
              <div className="course-engine-meta">
                白方视角 · {analysis.elapsed_ms} ms
                {analysis.from_cache ? ' · 缓存' : ''}
              </div>
            </div>
          ) : outcome ? (
            <div className="course-engine-empty">终局无需继续计算。</div>
          ) : (
            <div className="course-engine-empty">正在连接本地引擎…</div>
          )}
        </div>
      ) : null}

      <EngineSettingsDrawer
        context="课程"
        engine={engine}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </section>
  );
}
