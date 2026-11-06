import { useSyncExternalStore } from 'react';

const compactViewport =
  '(max-width: 760px), (max-width: 1180px) and (max-height: 600px)';

function subscribe(notify: () => void) {
  const media = window.matchMedia(compactViewport);
  media.addEventListener('change', notify);
  document.addEventListener('fullscreenchange', notify);
  return () => {
    media.removeEventListener('change', notify);
    document.removeEventListener('fullscreenchange', notify);
  };
}

export function useCompactReaderViewport() {
  return useSyncExternalStore(
    subscribe,
    // The full-screen reader can gain enough height to cross the compact breakpoint.
    () =>
      window.matchMedia(compactViewport).matches ||
      document.fullscreenElement === document.documentElement,
  );
}
