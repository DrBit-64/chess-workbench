export function RecordMovesButton({
  recording,
  onChange,
  disabled = false,
}: {
  recording: boolean;
  onChange: (recording: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      className="record-moves-toggle rounded px-2 py-1"
      type="button"
      aria-label="记录走棋"
      aria-pressed={recording}
      title={recording ? '关闭记录走棋' : '开启记录走棋'}
      disabled={disabled}
      onClick={() => onChange(!recording)}
    >
      <svg aria-hidden="true" width="20" height="20" viewBox="0 0 20 20">
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
  );
}
