export function positionLabel(position: {
  fen: string;
  san: string | null;
  is_mainline: boolean;
}) {
  const [, side, , , , move] = position.fen.split(' ');
  const at = `第 ${move} 回合 · ${side === 'w' ? '白方' : '黑方'}待走`;
  const where = position.san ? `${position.san} 后` : '起始局面';
  return `${at} · ${where} · ${position.is_mainline ? '实战主线' : '分析变例'}`;
}
