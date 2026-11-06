import { Chess, DEFAULT_POSITION } from 'chess.js';
import { expect, it, vi } from 'vitest';

import {
  findMissingChapterFens,
  loadChapterFens,
} from './chapterEnginePositions';

it('collects distinct playable positions from diagrams and games below a chapter', async () => {
  const game = new Chess();
  game.move('e4');
  const diagramFen = game.fen();
  game.move('e5');
  const childFen = game.fen();
  const mateFen = '7k/6Q1/5K2/8/8/8/8/8 b - - 0 1';
  function root(full_fen: string) {
    return { parent_id: null, full_fen };
  }
  const editorResponse = (occurrences: unknown[]) =>
    Response.json({ content_blocks: [], occurrences });
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(editorResponse([root(DEFAULT_POSITION)]))
    .mockResolvedValueOnce(editorResponse([root(diagramFen)]))
    .mockResolvedValueOnce(
      editorResponse([
        root(diagramFen),
        { parent_id: 'root', full_fen: childFen },
        { parent_id: 'branch', full_fen: mateFen },
      ]),
    );
  try {
    const signal = new AbortController().signal;
    expect(
      await loadChapterFens('book', [], ['intro', 'diagram', 'game'], signal),
    ).toEqual([diagramFen, childFen]);
    expect(fetch).toHaveBeenCalledWith(
      '/api/courses/book/editor/game',
      expect.objectContaining({ method: 'GET', signal }),
    );
  } finally {
    fetch.mockRestore();
  }
});

it('combines cache misses across a large chapter before running its analyses', async () => {
  const fens = Array.from({ length: 501 }, (_, i) =>
    DEFAULT_POSITION.replace(/1$/, String(i + 1)),
  );
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async (_, init) => {
      const { fens: batch } = JSON.parse(String(init?.body)) as {
        fens: string[];
      };
      return Response.json({
        missing_fens: batch.slice(0, 1),
        cached_fens: batch.slice(1),
      });
    });
  try {
    const misses = await findMissingChapterFens(
      fens,
      {
        multipv: 4,
        movetime_ms: 800,
        depth: null,
        threads: 1,
        hash_mb: 128,
        ponder: false,
      },
      new AbortController().signal,
    );
    expect(misses).toEqual([fens[0], fens[500]]);
    expect(fetch).toHaveBeenCalledTimes(2);
  } finally {
    fetch.mockRestore();
  }
});
