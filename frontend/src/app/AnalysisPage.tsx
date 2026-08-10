import {
  Alert,
  Button,
  Card,
  Drawer,
  Input,
  Radio,
  Segmented,
  Select,
  Slider,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { Chess } from 'chess.js';
import { useEffect, useMemo, useState } from 'react';
import { Chessboard } from 'react-chessboard';
import useSWR from 'swr';

import { fetchJson, requestJson } from '../logic/api/client';
import type {
  Analysis,
  AnalysisLine,
  EngineCapabilities,
  EngineGame,
  EngineGameReview,
  EngineParameters,
  Job,
} from '../logic/api/engineTypes';
import {
  FAST_MOVE_ANIMATION_MS,
  lichessSquareStyles,
} from './boardInteraction';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

function scoreLabel(line: AnalysisLine): string {
  if (line.mate !== null) return `#${line.mate}`;
  const pawns = (line.score_cp ?? 0) / 100;
  return `${pawns >= 0 ? '+' : ''}${pawns.toFixed(2)}`;
}

function whiteShare(line?: AnalysisLine): number {
  if (!line) return 50;
  if (line.mate !== null) return line.mate > 0 ? 100 : 0;
  const cp = Math.max(-1200, Math.min(1200, line.score_cp ?? 0));
  return 50 + 50 * (2 / (1 + Math.exp(-cp / 240)) - 1);
}

function compactNodes(nodes: number | null): string {
  if (nodes === null) return '—';
  if (nodes >= 1_000_000) return `${(nodes / 1_000_000).toFixed(1)}M`;
  if (nodes >= 1_000) return `${(nodes / 1_000).toFixed(1)}k`;
  return String(nodes);
}

export function AnalysisPage() {
  const { data: capabilities, error: capabilityError } =
    useSWR<EngineCapabilities>('/api/engine/capabilities', fetchJson);
  const [mode, setMode] = useState<'analysis' | 'play'>('analysis');
  const [fen, setFen] = useState(START_FEN);
  const [fenInput, setFenInput] = useState(START_FEN);
  const [parameters, setParameters] = useState<EngineParameters>({
    multipv: 4,
    movetime_ms: 800,
    depth: null,
    threads: 1,
    hash_mb: 128,
    ponder: false,
  });
  const [analysis, setAnalysis] = useState<Analysis>();
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string>();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selectedSquare, setSelectedSquare] = useState<string>();
  const [job, setJob] = useState<Job>();
  const [game, setGame] = useState<EngineGame>();
  const [review, setReview] = useState<EngineGameReview>();
  const [userColor, setUserColor] = useState<'white' | 'black'>('white');
  const [strength, setStrength] = useState(5);
  const [gameBusy, setGameBusy] = useState(false);

  useEffect(() => {
    if (capabilities)
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
    if (!job || !['queued', 'running'].includes(job.status)) return;
    const timer = window.setInterval(() => {
      void fetchJson<Job>(`/api/jobs/${job.id}`).then((fresh) => {
        setJob(fresh);
        if (fresh.status === 'failed') {
          setAnalysisError(
            fresh.last_error_message ?? '后台分析未能完成，请检查引擎状态。',
          );
        }
        const analysisId = fresh.result?.analysis_id;
        if (fresh.status === 'succeeded' && typeof analysisId === 'string') {
          void fetchJson<Analysis>(`/api/engine/analyses/${analysisId}`).then(
            setAnalysis,
          );
        }
      });
    }, 500);
    return () => window.clearInterval(timer);
  }, [job]);

  const activeJobId =
    job && ['queued', 'running'].includes(job.status) ? job.id : undefined;

  useEffect(() => {
    if (!activeJobId || typeof WebSocket === 'undefined') return;
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(
      `${scheme}//${window.location.host}/api/invalidations/ws`,
    );
    socket.onmessage = (event) => {
      try {
        const invalidation = JSON.parse(String(event.data)) as {
          resource_type: string;
          resource_id: string;
        };
        if (
          invalidation.resource_type !== 'job' ||
          invalidation.resource_id !== activeJobId
        )
          return;
        void fetchJson<Job>(`/api/jobs/${activeJobId}`).then((fresh) => {
          setJob(fresh);
          const analysisId = fresh.result?.analysis_id;
          if (fresh.status === 'succeeded' && typeof analysisId === 'string') {
            void fetchJson<Analysis>(`/api/engine/analyses/${analysisId}`).then(
              setAnalysis,
            );
          }
        });
      } catch {
        // Invalidations are only an optimization; interval polling remains the
        // authoritative recovery path for malformed frames and disconnects.
      }
    };
    return () => socket.close();
  }, [activeJobId]);

  const activeFen = mode === 'play' && game ? game.current_fen : fen;
  const boardSquareStyles = useMemo(() => {
    if (!selectedSquare) return {};
    try {
      return lichessSquareStyles(activeFen, selectedSquare);
    } catch {
      return {};
    }
  }, [activeFen, selectedSquare]);

  async function runAnalysis() {
    setAnalyzing(true);
    setAnalysisError(undefined);
    try {
      const result = await requestJson<Analysis>('/api/engine/analyses', {
        method: 'POST',
        body: JSON.stringify({ fen, parameters }),
      });
      setAnalysis(result);
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : '引擎分析失败');
    } finally {
      setAnalyzing(false);
    }
  }

  function applyFen() {
    try {
      const normalized = new Chess(fenInput).fen();
      setFen(normalized);
      setAnalysis(undefined);
      setSelectedSquare(undefined);
    } catch {
      void message.error('FEN 无效');
    }
  }

  function moveOnAnalysisBoard(
    source: string,
    target: string,
    promotion = 'q',
  ): boolean {
    const chess = new Chess(fen);
    try {
      const move = chess.move({ from: source, to: target, promotion });
      if (!move) return false;
    } catch {
      return false;
    }
    const next = chess.fen();
    setFen(next);
    setFenInput(next);
    setAnalysis(undefined);
    setSelectedSquare(undefined);
    return true;
  }

  async function createBackgroundAnalysis() {
    setAnalysisError(undefined);
    try {
      const created = await requestJson<Job>('/api/engine/analysis-jobs', {
        method: 'POST',
        body: JSON.stringify({
          fen,
          parameters: {
            ...parameters,
            movetime_ms: Math.max(8000, parameters.movetime_ms),
          },
          idempotency_key: crypto.randomUUID(),
        }),
      });
      setJob(created);
    } catch (error) {
      setAnalysisError(
        error instanceof Error ? error.message : '后台分析排队失败',
      );
    }
  }

  async function cancelBackgroundAnalysis() {
    if (!job) return;
    try {
      setJob(
        await requestJson<Job>(`/api/jobs/${job.id}/cancel`, {
          method: 'POST',
        }),
      );
    } catch (error) {
      setAnalysisError(
        error instanceof Error ? error.message : '取消后台分析失败',
      );
    }
  }

  async function startGame() {
    setGameBusy(true);
    try {
      const created = await requestJson<EngineGame>('/api/engine/games', {
        method: 'POST',
        body: JSON.stringify({ fen, user_color: userColor, strength }),
      });
      setGame(created);
      setReview(undefined);
    } finally {
      setGameBusy(false);
    }
  }

  async function moveInGame(source: string, target: string): Promise<boolean> {
    if (!game || game.status !== 'active') return false;
    const board = new Chess(game.current_fen);
    let uci = '';
    try {
      const move = board.move({ from: source, to: target, promotion: 'q' });
      if (!move) return false;
      uci = `${source}${target}${move.promotion ?? ''}`;
    } catch {
      return false;
    }
    setGameBusy(true);
    try {
      const updated = await requestJson<EngineGame>(
        `/api/engine/games/${game.id}/moves`,
        {
          method: 'POST',
          body: JSON.stringify({ uci, expected_version: game.version }),
        },
      );
      setGame(updated);
      setSelectedSquare(undefined);
      return true;
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '落子失败');
      return false;
    } finally {
      setGameBusy(false);
    }
  }

  async function reviewGame() {
    if (!game) return;
    setGameBusy(true);
    try {
      setReview(
        await requestJson<EngineGameReview>(
          `/api/engine/games/${game.id}/review`,
          { method: 'POST' },
        ),
      );
    } finally {
      setGameBusy(false);
    }
  }

  async function saveReviewDraft() {
    if (!game || !review) return;
    const saved = await requestJson<{ course_id: string }>(
      `/api/engine/games/${game.id}/review/course-draft`,
      {
        method: 'POST',
        body: JSON.stringify({
          title: `引擎对局复盘 ${new Date().toLocaleDateString()}`,
          finding_plies: review.findings.map((item) => item.ply),
        }),
      },
    );
    window.location.assign(`/learn/${saved.course_id}`);
  }

  function selectOwnPiece(square: string) {
    try {
      const board = new Chess(activeFen);
      const piece = board.get(square as Parameters<typeof board.get>[0]);
      const expectedColor =
        mode === 'play' && game
          ? game.user_color === 'white'
            ? 'w'
            : 'b'
          : board.turn();
      setSelectedSquare(
        piece?.color === board.turn() && piece.color === expectedColor
          ? square
          : undefined,
      );
    } catch {
      setSelectedSquare(undefined);
    }
  }

  function onSquareClick(square: string) {
    if (!selectedSquare) {
      selectOwnPiece(square);
      return;
    }
    if (selectedSquare === square) {
      setSelectedSquare(undefined);
      return;
    }
    if (mode === 'analysis') moveOnAnalysisBoard(selectedSquare, square);
    else void moveInGame(selectedSquare, square);
  }

  const topLine = analysis?.lines[0];
  const gaugeWhite = whiteShare(topLine);
  return (
    <main className="mx-auto max-w-[1600px] p-4 lg:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Typography.Title level={2} className="mb-1!">
            引擎工作台
          </Typography.Title>
          <Typography.Text type="secondary">
            评分固定采用白方视角；正值对白方有利，负值对黑方有利。
          </Typography.Text>
        </div>
        <Segmented
          aria-label="工作台模式"
          value={mode}
          onChange={(value) => setMode(value as 'analysis' | 'play')}
          options={[
            { label: '局面分析', value: 'analysis' },
            { label: '指定局面对弈', value: 'play' },
          ]}
        />
      </div>
      {capabilityError ? <Alert type="error" title="无法读取引擎状态" /> : null}
      {capabilities && !capabilities.available ? (
        <Alert
          className="mb-4"
          type="warning"
          showIcon
          title="尚未安装 Stockfish"
          description="在仓库根目录运行 make install-stockfish，然后重启 API。"
        />
      ) : null}
      <div className="analysis-grid">
        <section className="analysis-board-wrap">
          {mode === 'analysis' ? (
            <div
              className="evaluation-gauge"
              aria-label={`白方胜率刻度 ${gaugeWhite.toFixed(0)}%`}
            >
              <div
                className="evaluation-gauge-white"
                style={{ height: `${gaugeWhite}%` }}
              />
              <span
                className={gaugeWhite >= 50 ? 'text-stone-900' : 'text-white'}
              >
                {topLine ? scoreLabel(topLine) : '—'}
              </span>
            </div>
          ) : null}
          <div className="min-w-0 flex-1">
            <Chessboard
              id="analysis-board"
              position={activeFen}
              animationDuration={FAST_MOVE_ANIMATION_MS}
              boardOrientation={
                mode === 'play' && game ? game.user_color : 'white'
              }
              onPieceDrop={(source, target) => {
                if (mode === 'analysis')
                  return moveOnAnalysisBoard(source, target);
                void moveInGame(source, target);
                return false;
              }}
              onPieceDragBegin={(_, source) => selectOwnPiece(source)}
              onPieceDragEnd={() => setSelectedSquare(undefined)}
              onSquareClick={onSquareClick}
              customSquareStyles={boardSquareStyles}
              customBoardStyle={{
                borderRadius: '6px',
                boxShadow: '0 12px 30px #1c191733',
              }}
            />
          </div>
        </section>
        {mode === 'analysis' ? (
          <Card className="analysis-panel" styles={{ body: { padding: 0 } }}>
            <div className="engine-header">
              <div>
                <Typography.Text strong>
                  {analysis?.engine_name ??
                    capabilities?.engine_name ??
                    'Stockfish'}
                  {analysis?.engine_version
                    ? ` ${analysis.engine_version}`
                    : ''}
                </Typography.Text>
                <div className="text-xs text-stone-600">
                  深度 {analysis?.depth ?? '—'} ·{' '}
                  {compactNodes(analysis?.nodes ?? null)} 节点 ·{' '}
                  {analysis?.elapsed_ms ?? 0} ms
                  {analysis?.from_cache ? ' · 缓存' : ''}
                </div>
              </div>
              <Space>
                <Button onClick={() => setSettingsOpen(true)}>设置</Button>
                <Button
                  type="primary"
                  loading={analyzing}
                  disabled={
                    !capabilities?.available && !capabilities?.syzygy_available
                  }
                  onClick={() => void runAnalysis()}
                >
                  分析
                </Button>
              </Space>
            </div>
            {analysisError ? (
              <Alert type="error" showIcon title={analysisError} />
            ) : null}
            {analyzing ? (
              <div className="grid min-h-48 place-items-center">
                <Spin description="Stockfish 正在计算" />
              </div>
            ) : analysis?.lines.length ? (
              <div className="pv-list" aria-label="引擎主变">
                {analysis.lines.map((line) => (
                  <button
                    key={line.rank}
                    className="pv-row"
                    onClick={() => {
                      const move = line.uci[0];
                      if (move)
                        moveOnAnalysisBoard(
                          move.slice(0, 2),
                          move.slice(2, 4),
                          move.slice(4, 5) || 'q',
                        );
                    }}
                  >
                    <span className="pv-rank">{line.rank}</span>
                    <span className="pv-score">{scoreLabel(line)}</span>
                    <span className="pv-moves">{line.san.join(' ')}</span>
                    {line.wdl ? (
                      <span className="pv-wdl" title="胜 / 和 / 负（白方视角）">
                        {line.wdl[0]} / {line.wdl[1]} / {line.wdl[2]}
                      </span>
                    ) : null}
                  </button>
                ))}
              </div>
            ) : (
              <div className="p-8 text-center text-stone-600">
                点击“分析”获取默认 4 条推荐线路。
              </div>
            )}
            <div className="border-t border-stone-200 p-4">
              <Space wrap>
                <Button
                  disabled={!capabilities?.available}
                  onClick={() => void createBackgroundAnalysis()}
                >
                  后台深度分析
                </Button>
                {job ? (
                  <Tag
                    className={
                      job.status === 'succeeded'
                        ? 'analysis-success-tag'
                        : undefined
                    }
                    color={job.status === 'succeeded' ? undefined : 'blue'}
                  >
                    {job.status}
                  </Tag>
                ) : null}
                {job && ['queued', 'running'].includes(job.status) ? (
                  <Button
                    danger
                    onClick={() => void cancelBackgroundAnalysis()}
                  >
                    取消后台分析
                  </Button>
                ) : null}
                <Tag>
                  {analysis?.source === 'tablebase'
                    ? 'Syzygy 精确结果'
                    : 'Stockfish 估值'}
                </Tag>
              </Space>
            </div>
          </Card>
        ) : (
          <Card title="指定局面对弈" className="analysis-panel">
            {!game ? (
              <Space orientation="vertical" className="w-full" size="large">
                <div>
                  <Typography.Text strong>执棋颜色</Typography.Text>
                  <Radio.Group
                    className="mt-2 block"
                    value={userColor}
                    onChange={(e) => setUserColor(e.target.value)}
                  >
                    <Radio.Button value="white">白方</Radio.Button>
                    <Radio.Button value="black">黑方</Radio.Button>
                  </Radio.Group>
                </div>
                <div>
                  <Typography.Text strong>强度：{strength}/8</Typography.Text>
                  <Slider
                    min={1}
                    max={8}
                    value={strength}
                    onChange={setStrength}
                    marks={{ 1: '轻', 5: '强', 8: '最强' }}
                  />
                </div>
                <Button
                  type="primary"
                  loading={gameBusy}
                  disabled={!capabilities?.available}
                  onClick={() => void startGame()}
                >
                  从当前局面开始
                </Button>
              </Space>
            ) : (
              <>
                <Space wrap className="mb-4">
                  <Tag>{game.user_color === 'white' ? '执白' : '执黑'}</Tag>
                  <Tag>强度 {game.strength}/8</Tag>
                  <Tag
                    className={
                      game.status === 'finished'
                        ? 'analysis-success-tag'
                        : undefined
                    }
                    color={game.status === 'finished' ? undefined : 'blue'}
                  >
                    {game.status}
                  </Tag>
                  <Button onClick={() => setGame(undefined)}>新对局</Button>
                </Space>
                <div className="game-move-list">
                  {game.moves.map((move) => (
                    <span
                      key={move.ply}
                      className={move.actor === 'user' ? 'font-semibold' : ''}
                    >
                      {move.ply}. {move.san}
                    </span>
                  ))}
                </div>
                <Space className="mt-4" wrap>
                  <Button
                    loading={gameBusy}
                    disabled={!game.moves.length}
                    onClick={() => void reviewGame()}
                  >
                    复盘我的决策
                  </Button>
                  {review ? (
                    <Button
                      type="primary"
                      onClick={() => void saveReviewDraft()}
                    >
                      保存为课程草稿
                    </Button>
                  ) : null}
                </Space>
                {review ? (
                  <div className="mt-4 grid gap-2">
                    {review.findings.map((finding) => (
                      <Alert
                        key={finding.ply}
                        type={
                          finding.verdict === 'blunder'
                            ? 'error'
                            : finding.verdict === 'mistake'
                              ? 'warning'
                              : 'info'
                        }
                        title={`第 ${finding.ply} ply：${finding.played_uci} → 推荐 ${finding.best_uci}`}
                        description={`损失 ${(finding.loss_cp / 100).toFixed(2)} 兵 · ${finding.verdict}`}
                      />
                    ))}
                  </div>
                ) : null}
              </>
            )}
          </Card>
        )}
      </div>
      <Space.Compact className="mt-4 w-full">
        <Input
          aria-label="分析局面 FEN"
          value={fenInput}
          onChange={(event) => setFenInput(event.target.value)}
          onPressEnter={applyFen}
        />
        <Button onClick={applyFen}>载入 FEN</Button>
      </Space.Compact>
      <Drawer
        title="本地引擎设置"
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      >
        <Typography.Paragraph type="secondary">
          设置层级参照 Lichess；ChessWorkbench 为对比学习默认显示 4
          条线路。所有资源有服务器上限，因此不提供无限分析。
        </Typography.Paragraph>
        <Typography.Text strong>引擎</Typography.Text>
        <Select
          aria-label="分析引擎"
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
        <Typography.Text strong>线路：{parameters.multipv}</Typography.Text>
        <Slider
          min={1}
          max={5}
          value={parameters.multipv}
          onChange={(multipv) => setParameters({ ...parameters, multipv })}
          marks={{ 1: '1', 3: '3', 4: '4', 5: '5' }}
        />
        <Typography.Text strong>线程：{parameters.threads}</Typography.Text>
        <Slider
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
          description="本地交互分析不在后台猜测对手着法，避免额外 CPU 占用。"
        />
      </Drawer>
    </main>
  );
}
