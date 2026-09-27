import { formatMoveNotation } from './moveNotation';

export function MoveNotation({
  san,
  nags = [],
  active = false,
}: {
  san: string;
  nags?: readonly number[];
  active?: boolean;
}) {
  const { move, annotations } = formatMoveNotation(san, nags);
  return (
    <>
      <span>{move}</span>
      {annotations.map(({ code, symbol, label, color }) => (
        <span
          key={code}
          title={label}
          className={`ml-0.5 font-semibold ${active ? 'text-white' : color}`}
        >
          {symbol}
        </span>
      ))}
    </>
  );
}
