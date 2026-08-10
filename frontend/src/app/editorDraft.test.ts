import { describe, expect, it } from 'vitest';

import { createDraftState, editorDraftReducer } from './editorDraft';

describe('editorDraftReducer', () => {
  it('undoes and redoes Markdown and source edits in exact order', () => {
    let state = createDraftState({ markdown: 'first', sourceSpanIds: [] });
    state = editorDraftReducer(state, { type: 'markdown', markdown: 'second' });
    state = editorDraftReducer(state, {
      type: 'sources',
      sourceSpanIds: ['span-1'],
    });
    expect(state.present).toEqual({
      markdown: 'second',
      sourceSpanIds: ['span-1'],
    });

    state = editorDraftReducer(state, { type: 'undo' });
    expect(state.present).toEqual({ markdown: 'second', sourceSpanIds: [] });
    state = editorDraftReducer(state, { type: 'undo' });
    expect(state.present.markdown).toBe('first');
    state = editorDraftReducer(state, { type: 'redo' });
    expect(state.present.markdown).toBe('second');
  });

  it('drops redo history after a divergent edit and ignores no-op actions', () => {
    const initial = createDraftState({ markdown: 'a', sourceSpanIds: [] });
    const unchanged = editorDraftReducer(initial, {
      type: 'markdown',
      markdown: 'a',
    });
    expect(unchanged).toBe(initial);
    const edited = editorDraftReducer(initial, {
      type: 'markdown',
      markdown: 'b',
    });
    const undone = editorDraftReducer(edited, { type: 'undo' });
    const divergent = editorDraftReducer(undone, {
      type: 'markdown',
      markdown: 'c',
    });
    expect(divergent.future).toEqual([]);
    expect(editorDraftReducer(divergent, { type: 'redo' })).toBe(divergent);
  });

  it('reset establishes a clean baseline with no local history', () => {
    const edited = editorDraftReducer(
      createDraftState({ markdown: 'a', sourceSpanIds: [] }),
      { type: 'markdown', markdown: 'b' },
    );
    expect(
      editorDraftReducer(edited, {
        type: 'reset',
        draft: { markdown: 'server', sourceSpanIds: ['span'] },
      }),
    ).toEqual({
      past: [],
      present: { markdown: 'server', sourceSpanIds: ['span'] },
      future: [],
    });
  });
});
