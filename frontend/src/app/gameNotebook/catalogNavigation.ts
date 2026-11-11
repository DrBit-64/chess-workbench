import { useLayoutEffect } from 'react';
import { useLocation } from 'react-router-dom';

// Preserve the exact list entry the user came from, without retaining scroll for a fresh visit.
const listScroll = new Map<string, number>();

export function useCatalogReturn(ready: boolean) {
  const location = useLocation();
  const entry = location.key;
  useLayoutEffect(() => {
    const offset = listScroll.get(entry);
    if (!ready || offset === undefined) return;
    window.scrollTo(0, offset);
    listScroll.delete(entry);
  }, [entry, ready]);
  return {
    state: { notebookBack: location.pathname + location.search },
    remember: () => listScroll.set(entry, window.scrollY),
  };
}
