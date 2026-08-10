export type EditorDraft = {
  markdown: string;
  sourceSpanIds: string[];
};

export type EditorDraftState = {
  past: EditorDraft[];
  present: EditorDraft;
  future: EditorDraft[];
};

export type EditorDraftAction =
  | { type: 'reset'; draft: EditorDraft }
  | { type: 'markdown'; markdown: string }
  | { type: 'sources'; sourceSpanIds: string[] }
  | { type: 'undo' }
  | { type: 'redo' };

export function createDraftState(draft: EditorDraft): EditorDraftState {
  return { past: [], present: draft, future: [] };
}

function push(state: EditorDraftState, present: EditorDraft): EditorDraftState {
  if (
    state.present.markdown === present.markdown &&
    state.present.sourceSpanIds.join('\0') === present.sourceSpanIds.join('\0')
  ) {
    return state;
  }
  return {
    past: [...state.past, state.present],
    present,
    future: [],
  };
}

export function editorDraftReducer(
  state: EditorDraftState,
  action: EditorDraftAction,
): EditorDraftState {
  switch (action.type) {
    case 'reset':
      return createDraftState(action.draft);
    case 'markdown':
      return push(state, { ...state.present, markdown: action.markdown });
    case 'sources':
      return push(state, {
        ...state.present,
        sourceSpanIds: [...action.sourceSpanIds],
      });
    case 'undo': {
      const previous = state.past.at(-1);
      if (!previous) return state;
      return {
        past: state.past.slice(0, -1),
        present: previous,
        future: [state.present, ...state.future],
      };
    }
    case 'redo': {
      const next = state.future[0];
      if (!next) return state;
      return {
        past: [...state.past, state.present],
        present: next,
        future: state.future.slice(1),
      };
    }
  }
}
