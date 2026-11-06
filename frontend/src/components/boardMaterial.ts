export const MATERIAL_ROLES = ['q', 'r', 'b', 'n', 'p'] as const;
export type MaterialRole = (typeof MATERIAL_ROLES)[number];
export type MaterialSide = Record<MaterialRole, number>;

const VALUES: Record<MaterialRole, number> = { q: 9, r: 5, b: 3, n: 3, p: 1 };

// Like Lichess ui/lib/src/game/material.ts, compare the current pieces by role.
// No starting-position or capture-history assumption: diagram FENs and promotions work too.
export function boardMaterial(fen: string) {
  const white: MaterialSide = { q: 0, r: 0, b: 0, n: 0, p: 0 };
  const black: MaterialSide = { ...white };
  const placement = fen === 'start' ? '' : fen.split(' ')[0];
  for (const char of placement) {
    const role = char.toLowerCase() as MaterialRole;
    if (!(role in white)) continue;
    const counts = char === role ? black : white;
    counts[role]++;
  }
  let score = 0;
  for (const role of MATERIAL_ROLES) {
    const difference = white[role] - black[role];
    white[role] = Math.max(difference, 0);
    black[role] = Math.max(-difference, 0);
    score += difference * VALUES[role];
  }
  return { white, black, score };
}
