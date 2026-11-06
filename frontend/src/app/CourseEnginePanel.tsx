import {
  Alert,
  Button,
  Drawer,
  Progress,
  Select,
  Slider,
  Space,
  Spin,
  Switch,
  Typography,
} from 'antd';
import { useState } from 'react';

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
  lookupFailed: boolean;
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
    terminal,
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
                  : terminal
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
                  !sectionProgress.running && sectionProgress.failed
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
                {sectionProgress.lookupFailed
                  ? '章节或缓存读取失败，未启动分析'
                  : sectionProgress.total === 0
                    ? sectionProgress.cached
                      ? `全部 ${sectionProgress.cached} 个局面已有缓存`
                      : '没有可分析的局面'
                    : sectionProgress.failed
                      ? `${sectionProgress.failed} 个局面失败，可再次运行补齐`
                      : '本小节分析已保存'}
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
          ) : terminal ? (
            <div className="course-engine-empty">终局无需继续计算。</div>
          ) : (
            <div className="course-engine-empty">正在连接本地引擎…</div>
          )}
        </div>
      ) : null}

      <Drawer
        title="课程棋盘引擎设置"
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      >
        <div className="mb-6 flex items-center justify-between gap-4">
          <div>
            <Typography.Text strong>实时分析</Typography.Text>
            <div className="text-xs text-stone-600">切换局面后自动重新计算</div>
          </div>
          <Switch
            aria-label="设置中开启实时分析"
            checked={enabled}
            onChange={setEnabled}
          />
        </div>
        <Typography.Text strong>引擎</Typography.Text>
        <Select
          aria-label="课程分析引擎"
          className="mb-6 mt-2 w-full"
          disabled
          value={capabilities?.engine_name ?? 'Stockfish 18'}
          options={[
            {
              value: capabilities?.engine_name ?? 'Stockfish 18',
              label: capabilities?.engine_name ?? 'Stockfish 18',
            },
          ]}
        />
        <Typography.Text strong>搜索时间</Typography.Text>
        <Select
          aria-label="课程引擎搜索时间"
          className="mb-6 mt-2 w-full"
          value={parameters.movetime_ms}
          onChange={(movetime_ms) =>
            setParameters({ ...parameters, movetime_ms })
          }
          options={(
            capabilities?.time_presets_ms ?? [500, 800, 2000, 4000, 8000]
          ).map((value) => ({
            value,
            label: value < 1000 ? `${value} ms` : `${value / 1000} 秒`,
          }))}
        />
        <Typography.Text strong>分析线路：{parameters.multipv}</Typography.Text>
        <Slider
          ariaLabelForHandle="课程引擎线路数"
          min={1}
          max={capabilities?.multipv_max ?? 5}
          value={parameters.multipv}
          onChange={(multipv) => setParameters({ ...parameters, multipv })}
          marks={{ 1: '1', 3: '3', 4: '4', 5: '5' }}
        />
        <div className="mt-6 flex items-center justify-between gap-4">
          <div>
            <Typography.Text strong>棋盘推荐箭头</Typography.Text>
            <div className="text-xs text-stone-600">显示每条线路的第一步</div>
          </div>
          <Switch
            aria-label="显示引擎推荐箭头"
            checked={showArrows}
            onChange={setShowArrows}
          />
        </div>
        <div className="mt-5">
          <Typography.Text strong>推荐箭头：{arrowCount}</Typography.Text>
          <Slider
            ariaLabelForHandle="引擎推荐箭头数量"
            disabled={!showArrows}
            min={1}
            max={Math.min(parameters.multipv, 4)}
            value={arrowCount}
            onChange={setArrowCount}
            marks={{
              1: '1',
              [Math.min(parameters.multipv, 4)]: String(
                Math.min(parameters.multipv, 4),
              ),
            }}
          />
        </div>
        <Typography.Text strong>线程：{parameters.threads}</Typography.Text>
        <Slider
          ariaLabelForHandle="课程引擎线程数"
          min={1}
          max={capabilities?.max_threads ?? 4}
          value={parameters.threads}
          onChange={(threads) => setParameters({ ...parameters, threads })}
          marks={{
            1: '1',
            [capabilities?.max_threads ?? 4]: String(
              capabilities?.max_threads ?? 4,
            ),
          }}
        />
        <Typography.Text strong>内存：{parameters.hash_mb} MB</Typography.Text>
        <Select
          aria-label="课程引擎内存"
          className="mt-2 w-full"
          value={parameters.hash_mb}
          onChange={(hash_mb) => setParameters({ ...parameters, hash_mb })}
          options={[16, 32, 64, 128, 256, 512, 1024]
            .filter((value) => value <= (capabilities?.max_hash_mb ?? 1024))
            .map((value) => ({ value, label: `${value} MB` }))}
        />
        <Alert
          className="mt-6"
          type="info"
          title="Ponder 关闭"
          description="课程阅读只分析当前局面，不在后台猜测下一步，避免额外 CPU 占用。"
        />
      </Drawer>
    </section>
  );
}
