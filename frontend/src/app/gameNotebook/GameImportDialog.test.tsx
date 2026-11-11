import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { GameImportDialog } from './GameImportDialog';

it('retries an explicitly selected duplicate copy with the same request ID and original PGN', async () => {
  const pgn = '[Event "Test"]\n\n1. e4 *';
  const candidate = {
    index: 0,
    white: '甲',
    black: '乙',
    date: '2026.11.07',
    result: '*',
    platform: null,
    source_url: null,
    existing_id: null,
    possible_duplicates: ['already-saved'],
  };
  const fetcher = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      Response.json({
        pgn,
        source_url: null,
        games: [candidate],
        duplicate_games: [],
      }),
    )
    .mockResolvedValueOnce(
      Response.json({ message: '请求暂时失败' }, { status: 503 }),
    )
    .mockResolvedValueOnce(
      Response.json({ games: [{ id: 'other', index: 0, created: true }] }),
    );
  const onImported = vi.fn();
  render(<GameImportDialog onClose={() => {}} onImported={onImported} />);
  fireEvent.change(screen.getByRole('textbox', { name: 'PGN 棋谱' }), {
    target: { value: pgn },
  });
  fireEvent.click(screen.getByRole('button', { name: '预览棋谱' }));
  fireEvent.change(
    await screen.findByRole('combobox', { name: '发现可能重复的棋谱' }),
    { target: { value: 'copy' } },
  );
  fireEvent.click(screen.getByRole('button', { name: '收录所选棋谱' }));
  expect((await screen.findByRole('alert')).textContent).toContain(
    '请求暂时失败',
  );
  fireEvent.click(screen.getByRole('button', { name: '收录所选棋谱' }));
  await waitFor(() => expect(onImported).toHaveBeenCalledOnce());
  const bodies = fetcher.mock.calls.slice(1).map(
    ([, request]) =>
      JSON.parse(String(request?.body)) as {
        pgn: string;
        selections: unknown;
        request_id: string;
      },
  );
  expect(bodies[0]).toMatchObject({
    pgn,
    selections: [{ index: 0, action: 'copy' }],
  });
  expect(bodies[0].request_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(bodies[1]).toEqual(bodies[0]);
});

it('retains a UTF-8 BOM from a PGN upload and rejects invalid UTF-8 without changing the previous text', async () => {
  render(<GameImportDialog onClose={() => {}} onImported={() => {}} />);
  const choose = screen.getByLabelText('选择 PGN 文件');
  const source = '\uFEFF[White "棋手"]\n\n1. e4 *\n';
  const inputFile = (bytes: Uint8Array) =>
    Object.assign(new File([], 'sample.pgn'), {
      arrayBuffer: async () => bytes.buffer,
    });
  fireEvent.change(choose, {
    target: { files: [inputFile(new TextEncoder().encode(source))] },
  });
  const pgn = screen.getByRole('textbox', {
    name: 'PGN 棋谱',
  }) as HTMLTextAreaElement;
  await waitFor(() => expect(pgn.value).toEqual(source));
  fireEvent.change(choose, {
    target: { files: [inputFile(Uint8Array.of(0xff))] },
  });
  expect((await screen.findByRole('alert')).textContent).toContain('UTF-8');
  expect(pgn.value).toEqual(source);
});
