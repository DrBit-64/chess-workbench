/** One presentation rule for review candidates and published course moves. */
const GLYPHS: Record<number, { symbol: string; label: string; color: string }> =
  {
    1: { symbol: '!', label: '好着', color: 'text-emerald-700' },
    2: { symbol: '?', label: '错着', color: 'text-rose-700' },
    3: { symbol: '!!', label: '妙着', color: 'text-emerald-700' },
    4: { symbol: '??', label: '败着', color: 'text-rose-700' },
    5: { symbol: '!?', label: '有趣着法', color: 'text-sky-700' },
    6: { symbol: '?!', label: '可疑着法', color: 'text-amber-700' },
    7: { symbol: '□', label: '唯一着法', color: 'text-stone-600' },
    10: { symbol: '=', label: '均势局面', color: 'text-stone-600' },
    13: { symbol: '∞', label: '局面不明', color: 'text-stone-600' },
    14: { symbol: '⩲', label: '白方稍优', color: 'text-stone-600' },
    15: { symbol: '⩱', label: '黑方稍优', color: 'text-stone-600' },
    16: { symbol: '±', label: '白方优势', color: 'text-stone-600' },
    17: { symbol: '∓', label: '黑方优势', color: 'text-stone-600' },
    18: { symbol: '+−', label: '白方胜势', color: 'text-stone-600' },
    19: { symbol: '-+', label: '黑方胜势', color: 'text-stone-600' },
    22: { symbol: '⨀', label: '楚茨文克', color: 'text-stone-600' },
    23: { symbol: '⨀', label: '楚茨文克', color: 'text-stone-600' },
    32: { symbol: '↑↑', label: '子力发展', color: 'text-stone-600' },
    36: { symbol: '↑', label: '主动权', color: 'text-stone-600' },
    40: { symbol: '→', label: '进攻', color: 'text-stone-600' },
    44: { symbol: '=∞', label: '优势补偿', color: 'text-stone-600' },
    132: { symbol: '⇆', label: '反击', color: 'text-stone-600' },
    133: { symbol: '⇆', label: '反击', color: 'text-stone-600' },
    138: { symbol: '⊕', label: '无暇多虑', color: 'text-stone-600' },
    139: { symbol: '⊕', label: '无暇多虑', color: 'text-stone-600' },
    140: { symbol: '∆', label: '意图', color: 'text-stone-600' },
    146: { symbol: 'N', label: '创新着法', color: 'text-stone-600' },
  };

const SUFFIX_NAGS: Record<string, number> = {
  '!': 1,
  '?': 2,
  '!!': 3,
  '??': 4,
  '!?': 5,
  '?!': 6,
};

export function formatMoveNotation(san: string, nags: readonly number[] = []) {
  const match = /([!?]{1,2})$/.exec(san.trim());
  const suffixNag = match ? SUFFIX_NAGS[match[1]] : undefined;
  const move = (match ? san.trim().slice(0, -match[1].length) : san.trim())
    .replace(/[X×]/g, 'x')
    .replace(/^0-0(?:-0)?/, (castle) => castle.replace(/0/g, 'O'));
  const codes =
    nags.length > 0 ? nags : suffixNag === undefined ? [] : [suffixNag];
  const annotations = [...new Set(codes)].map((code) => ({
    code,
    ...(GLYPHS[code] ?? {
      symbol: `$${code}`,
      label: `评注 ${code}`,
      color: 'text-stone-600',
    }),
  }));
  return { move, annotations };
}

export function moveNotationText(
  san: string,
  nags: readonly number[] = [],
): string {
  const { move, annotations } = formatMoveNotation(san, nags);
  return move + annotations.map(({ symbol }) => symbol).join('');
}
