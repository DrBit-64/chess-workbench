import { DEFAULT_POSITION } from 'chess.js';

import { requestJson } from '../logic/api/client';
import type { ModuleEditor } from '../logic/api/types';
import { indexScorePositions } from './scoreEvaluations';

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

export function courseScorePositions(
  editor: ModuleEditor | undefined,
  includeStart: boolean,
) {
  const nodes = editor?.occurrences ?? [];
  const parents = new Set(nodes.map((node) => node.parent_id));
  return indexScorePositions(
    nodes.map((node) => ({
      id: node.id,
      fen: node.full_fen,
      comment: node.context?.pgn_comment,
      hasContinuation: parents.has(node.id),
      analyze: includeStart || node.full_fen !== DEFAULT_POSITION,
    })),
  );
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
    const chapter = courseScorePositions(
      editor,
      hasBookBoard(editor, DEFAULT_POSITION),
    );
    for (const fen of chapter.fens) positions.add(fen);
  }
  return [...positions];
}
