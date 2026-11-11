import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { BookmarkEditor } from './BookmarkEditor';

it('keeps the draft through a failed save and includes a still-typed new tag on retry', async () => {
  const initial = { title: '换后', note: '原笔记', tags: ['残局'] };
  const onSave = vi
    .fn()
    .mockRejectedValueOnce(new Error('其他设备已修改'))
    .mockResolvedValueOnce(undefined);
  const onClose = vi.fn();
  const { rerender } = render(
    <BookmarkEditor
      initial={initial}
      suggestedTags={['残局', '换后']}
      onSave={onSave}
      onClose={onClose}
    />,
  );
  fireEvent.change(screen.getByLabelText('局面评语'), {
    target: { value: '我的草稿' },
  });
  fireEvent.change(screen.getByLabelText('添加标签'), {
    target: { value: '王的位置' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存' }));
  expect((await screen.findByRole('alert')).textContent).toContain(
    '其他设备已修改',
  );
  expect(onClose).not.toHaveBeenCalled();
  rerender(
    <BookmarkEditor
      initial={{ ...initial, note: '电脑上刚写的' }}
      suggestedTags={[]}
      onSave={onSave}
      onClose={onClose}
    />,
  );
  expect(screen.getByText('电脑上刚写的')).toBeTruthy();
  expect((screen.getByLabelText('局面评语') as HTMLTextAreaElement).value).toBe(
    '我的草稿',
  );
  fireEvent.click(screen.getByRole('button', { name: '移除标签 残局' }));
  fireEvent.click(screen.getByRole('button', { name: '保存' }));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(onSave).toHaveBeenLastCalledWith({
    title: '换后',
    note: '我的草稿',
    tags: ['王的位置'],
  });
});
