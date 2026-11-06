import { Chess, DEFAULT_POSITION } from 'chess.js';

import { requestJson } from '../logic/api/client';
import type {
  AnalysisCacheLookup,
  EngineParameters,
} from '../logic/api/engineTypes';
import type { ModuleEditor } from '../logic/api/types';

// A prose-only introduction can carry a synthetic initial-position root.
export function hasBookBoard(
  editor: ModuleEditor | undefined,
  fen: string | undefined,
): boolean {
  return Boolean(
    fen &&
    (fen !== DEFAULT_POSITION ||
      editor?.occurrences.some((node) => node.parent_id !== null) ||
      editor?.content_blocks.some((block) => block.kind === 'move_sequence')),
  );
}

export type BoardOutcome = 'white-wins' | 'black-wins' | 'draw';

export function boardOutcome(fen: string): BoardOutcome | undefined {
  try {
    const board = new Chess(fen);
    if (board.isCheckmate())
      return board.turn() === 'w' ? 'black-wins' : 'white-wins';
    // The FEN clock can establish the automatic 75-move draw, but a 50-move
    // draw needs a player's claim, which the position alone cannot establish.
    if (
      board.isStalemate() ||
      board.isInsufficientMaterial() ||
      Number(fen.split(' ')[4]) >= 150
    )
      return 'draw';
  } catch {
    return;
  }
}

export async function loadChapterFens(
  courseId: string,
  activeFens: readonly string[],
  descendantIds: readonly string[],
  signal: AbortSignal,
): Promise<string[]> {
  const positions = new Set(activeFens);
  for (const id of descendantIds) {
    const editor = await requestJson<ModuleEditor>(
      `/api/courses/${courseId}/editor/${id}`,
      { method: 'GET', signal },
    );
    const includeStartingPosition = hasBookBoard(editor, DEFAULT_POSITION);
    for (const node of editor.occurrences) {
      if (node.full_fen !== DEFAULT_POSITION || includeStartingPosition) {
        positions.add(node.full_fen);
      }
    }
  }
  return [...positions].filter((fen) => !boardOutcome(fen));
}

export async function findMissingChapterFens(
  fens: string[],
  parameters: EngineParameters,
  signal: AbortSignal,
): Promise<string[]> {
  // A parent chapter may combine many games in a single analysis request.
  const batchSize = 500;
  const missing: string[] = [];
  for (let i = 0; i < fens.length; i += batchSize) {
    const result = await requestJson<AnalysisCacheLookup>(
      '/api/engine/analyses/cache-lookup',
      {
        method: 'POST',
        signal,
        body: JSON.stringify({
          fens: fens.slice(i, i + batchSize),
          parameters,
        }),
      },
    );
    missing.push(...result.missing_fens);
  }
  return missing;
}
