import {
  Alert,
  Button,
  Drawer,
  Select,
  Slider,
  Space,
  Spin,
  Switch,
  Typography,
} from 'antd';
import { Chess } from 'chess.js';
import type { ComponentProps } from 'react';
import { useEffect, useMemo, useState } from 'react';
import { Chessboard } from 'react-chessboard';
import useSWR from 'swr';

import { fetchJson, requestJson } from '../logic/api/client';
import type {
  Analysis,
  AnalysisLine,
  EngineCapabilities,
  EngineParameters,
} from '../logic/api/engineTypes';

const DEFAULT_PARAMETERS: EngineParameters = {
  multipv: 4,
  movetime_ms: 800,
  depth: null,
  threads: 1,
  hash_mb: 128,
  ponder: false,
};

const ARROW_COLORS = [
  'rgba(57, 91, 143, 0.78)',
  'rgba(57, 91, 143, 0.62)',
  'rgba(57, 91, 143, 0.48)',
  'rgba(57, 91, 143, 0.36)',
];

export type CourseEngineArrow = NonNullable<
  ComponentProps<typeof Chessboard>['customArrows']
>[number];
type BoardSquare = CourseEngineArrow[0];

function scoreLabel(line: AnalysisLine): string {
  if (line.mate !== null) return `#${line.mate}`;
  const pawns = (line.score_cp ?? 0) / 100;
  return `${pawns >= 0 ? '+' : ''}${pawns.toFixed(2)}`;
}

function isTerminal(fen: string): boolean {
  try {
    return new Chess(fen).isGameOver();
  } catch {
    return false;
  }
}

export function CourseEnginePanel({
  fen,
  onArrowsChange,
}: {
  fen: string;
  onArrowsChange: (arrows: CourseEngineArrow[]) => void;
}) {
  const [enabled, setEnabled] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showArrows, setShowArrows] = useState(true);
  const [arrowCount, setArrowCount] = useState(3);
  const [parameters, setParameters] =
    useState<EngineParameters>(DEFAULT_PARAMETERS);
  const [analysis, setAnalysis] = useState<Analysis>();
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string>();
  const { data: capabilities, error: capabilityError } =
    useSWR<EngineCapabilities>(
      enabled ? '/api/engine/capabilities' : null,
      fetchJson,
    );

  useEffect(() => {
    if (!capabilities) return;
    setParameters({
      multipv: capabilities.default_parameters.multipv ?? 4,
      movetime_ms: capabilities.default_parameters.movetime_ms ?? 800,
      depth: capabilities.default_parameters.depth ?? null,
      threads: capabilities.default_parameters.threads ?? 1,
      hash_mb: capabilities.default_parameters.hash_mb ?? 128,
      ponder: false,
    });
  }, [capabilities]);

  useEffect(() => {
    setArrowCount((current) => Math.min(current, parameters.multipv, 4));
  }, [parameters.multipv]);

  useEffect(() => {
    if (!enabled) {
      setAnalysis(undefined);
      setAnalysisError(undefined);
      setAnalyzing(false);
      return;
    }
    if (!capabilities || isTerminal(fen)) {
      setAnalysis(undefined);
      setAnalyzing(false);
      return;
    }
    if (!capabilities.available && !capabilities.syzygy_available) {
      setAnalysis(undefined);
      setAnalyzing(false);
      setAnalysisError(
        capabilities.install_hint ??
          'Stockfish 尚未安装，请先运行 make install-stockfish。',
      );
      return;
    }

    const controller = new AbortController();
    setAnalysis(undefined);
    setAnalysisError(undefined);
    setAnalyzing(true);
    const timer = window.setTimeout(() => {
      void requestJson<Analysis>('/api/engine/analyses', {
        method: 'POST',
        signal: controller.signal,
        body: JSON.stringify({ fen, parameters }),
      })
        .then((result) => {
          if (!controller.signal.aborted) setAnalysis(result);
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setAnalysisError(
            error instanceof Error ? error.message : '实时引擎分析失败',
          );
        })
        .finally(() => {
          if (!controller.signal.aborted) setAnalyzing(false);
        });
    }, 220);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [capabilities, enabled, fen, parameters]);

  const arrows = useMemo<CourseEngineArrow[]>(() => {
    if (!enabled || !showArrows || !analysis) return [];
    return analysis.lines
      .slice(0, Math.min(arrowCount, 4))
      .flatMap((line, index) => {
        const move = line.uci[0];
        if (!move) return [];
        return [
          [
            move.slice(0, 2) as BoardSquare,
            move.slice(2, 4) as BoardSquare,
            ARROW_COLORS[index],
          ],
        ];
      });
  }, [analysis, arrowCount, enabled, showArrows]);

  useEffect(() => {
    onArrowsChange(arrows);
    return () => onArrowsChange([]);
  }, [arrows, onArrowsChange]);

  const terminal = isTerminal(fen);

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
        <Button
          size="small"
          aria-label="课程引擎设置"
          onClick={() => setSettingsOpen(true)}
        >
          设置
        </Button>
      </div>

      {enabled ? (
        <div aria-live="polite">
          {capabilityError ? (
            <Alert type="error" showIcon title="无法读取本地引擎状态" />
          ) : analysisError ? (
            <Alert type="error" showIcon title={analysisError} />
          ) : analyzing ? (
            <div className="course-engine-loading">
              <Spin size="small" />
              <span>分析当前局面…</span>
            </div>
          ) : analysis?.lines.length ? (
            <div className="course-pv-list" aria-label="当前局面引擎线路">
              {analysis.lines.map((line) => (
                <div className="course-pv-row" key={line.rank}>
                  <span className="course-pv-rank">{line.rank}</span>
                  <span className="course-pv-score">{scoreLabel(line)}</span>
                  <span className="course-pv-moves">{line.san.join(' ')}</span>
                </div>
              ))}
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
            setParameters((current) => ({ ...current, movetime_ms }))
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
          onChange={(multipv) =>
            setParameters((current) => ({ ...current, multipv }))
          }
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
          onChange={(threads) =>
            setParameters((current) => ({ ...current, threads }))
          }
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
          onChange={(hash_mb) =>
            setParameters((current) => ({ ...current, hash_mb }))
          }
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
