import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { ApiError } from '../../logic/api/client';
import { ReviewNoteEditor } from './ReviewNoteEditor';

it('preserves the in-progress move note and shows the other device’s edit before retrying', async () => {
  const save = vi
    .fn()
    .mockRejectedValueOnce(new ApiError('stale_version', 409))
    .mockResolvedValueOnce(undefined);
  const close = vi.fn();
  render(
    <ReviewNoteEditor
      target={{
        kind: 'move',
        nodeId: 'black24',
        text: '旧想法',
        version: 1,
        position: '24... Kf8',
      }}
      reload={async () => ({ text: '手机里更新的想法', version: 2 })}
      onSave={save}
      onClose={close}
    />,
  );

  const input = screen.getByRole('textbox', {
    name: '棋步评语',
  }) as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: '电脑里正在补写的变化' } });
  const button = screen.getByRole('button', { name: /保\s*存/ });
  fireEvent.click(button);
  await screen.findByText('手机里更新的想法');
  expect(input.value).toBe('电脑里正在补写的变化');
  expect(close).not.toHaveBeenCalled();
  fireEvent.click(button);
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
  expect(save.mock.calls).toEqual([
    ['电脑里正在补写的变化', 1],
    ['电脑里正在补写的变化', 2],
  ]);
});
