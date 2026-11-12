// PGN stores base time in seconds; online chess displays minutes + increment in seconds.
function duration(seconds: number): string {
  if (seconds >= 86400 && seconds % 86400 === 0) return `${seconds / 86400} 天`;
  if (seconds >= 3600 && seconds % 3600 === 0) return `${seconds / 3600} 小时`;
  if (seconds >= 60 && seconds % 60 === 0) return `${seconds / 60} 分钟`;
  return `${seconds} 秒`;
}

export function gameTimeControl(value: string | null): string {
  if (!value || value === '?') return '未记录';
  if (value === '-') return '不限时';
  return value
    .split(':')
    .map((stage) => {
      const increment = /^(\d+)\+(\d+)$/.exec(stage);
      if (increment) {
        const base = Number(increment[1]);
        return base % 60 === 0
          ? `${base / 60}+${increment[2]}`
          : `${base} 秒 + ${increment[2]} 秒/步`;
      }
      const period = /^(\d+)\/(\d+)$/.exec(stage);
      if (period) {
        const length = duration(Number(period[2]));
        return period[1] === '1'
          ? `每步 ${length}`
          : `${period[1]} 步 / ${length}`;
      }
      if (/^\d+$/.test(stage)) return duration(Number(stage));
      if (/^\*\d+$/.test(stage))
        return `沙漏 ${duration(Number(stage.slice(1)))}`;
      return stage;
    })
    .join('，');
}
