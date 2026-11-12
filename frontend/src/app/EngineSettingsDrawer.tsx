import { Alert, Drawer, Select, Slider, Switch, Typography } from 'antd';
import type { useCourseEngine } from './useCourseEngine';

export function EngineSettingsDrawer({
  context,
  engine,
  open,
  onClose,
}: {
  context: '课程' | '复盘';
  engine: ReturnType<typeof useCourseEngine>;
  open: boolean;
  onClose: () => void;
}) {
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
  } = engine;
  return (
    <Drawer title={context + '棋盘引擎设置'} open={open} onClose={onClose}>
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
        aria-label={context + '分析引擎'}
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
        aria-label={context + '引擎搜索时间'}
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
        ariaLabelForHandle={context + '引擎线路数'}
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
        ariaLabelForHandle={context + '引擎线程数'}
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
        aria-label={context + '引擎内存'}
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
        description={
          context === '课程'
            ? '课程阅读只分析当前局面，不在后台猜测下一步，避免额外 CPU 占用。'
            : '实时分析跟随当前局面，走谱后切换。'
        }
      />
    </Drawer>
  );
}
