import { useSyncExternalStore } from 'react';

const compactViewport =
  '(max-width: 760px), (max-width: 1180px) and (max-height: 600px)';

function subscribe(notify: () => void) {
  const media = window.matchMedia(compactViewport);
  media.addEventListener('change', notify);
  return () => media.removeEventListener('change', notify);
}

export function useCompactReaderViewport() {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(compactViewport).matches,
  );
}
