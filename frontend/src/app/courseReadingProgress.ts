import { useLayoutEffect, useRef } from 'react';

export type CourseReaderPanel = 'score' | 'source' | 'chapters';

interface ReadingPlace {
  moduleId: string;
  occurrenceId?: string;
  sourceSpanId?: string;
  sourceOccurrenceId: string | null;
  panel: CourseReaderPanel;
  leftPane: 'chapters' | 'source';
}

function courseKey(courseId: string) {
  return `chess-workbench.reader.v1.${courseId}`;
}

function readObject(key: string): Record<string, unknown> | undefined {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return;
    const value: unknown = JSON.parse(raw);
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return value as Record<string, unknown>;
    }
  } catch {
    // The reader also works when browser storage is unavailable.
  }
}

function writeObject(key: string, value: object) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // A quota or privacy setting must not interrupt reading.
  }
}

export function readReadingPlace(
  courseId: string,
  search: URLSearchParams,
): ReadingPlace | undefined {
  const saved = readObject(courseKey(courseId));
  if (!saved || typeof saved.moduleId !== 'string') return;
  // A link to an explicit move or a different chapter takes precedence.
  const requested = search.get('module');
  if (search.has('occurrence') || (requested && requested !== saved.moduleId))
    return;
  const occurrenceId =
    typeof saved.occurrenceId === 'string' ? saved.occurrenceId : undefined;
  // Older bookmarks recorded a fallback page even when only the score had
  // been read. Keep their manual page if the source panel had been opened.
  const lastSourceMove =
    saved.sourceOccurrenceId === undefined &&
    (saved.panel === 'source' || saved.leftPane === 'source')
      ? occurrenceId
      : saved.sourceOccurrenceId;
  return {
    moduleId: saved.moduleId,
    occurrenceId,
    sourceSpanId:
      typeof saved.sourceSpanId === 'string' ? saved.sourceSpanId : undefined,
    sourceOccurrenceId:
      typeof lastSourceMove === 'string' ? lastSourceMove : null,
    panel:
      saved.panel === 'source' || saved.panel === 'chapters'
        ? saved.panel
        : 'score',
    leftPane: saved.leftPane === 'source' ? 'source' : 'chapters',
  };
}

export function saveReadingPlace(courseId: string, place: ReadingPlace) {
  writeObject(courseKey(courseId), place);
}

interface TextPlace {
  top: number;
  anchor?: string;
  paragraph?: number;
  // Proportion inside the paragraph, or pixel gap above it.
  fraction?: number;
  gap?: number;
}

export function captureText(scroller: HTMLElement): TextPlace {
  const top = scroller.getBoundingClientRect().top;
  const place: TextPlace = { top: scroller.scrollTop };
  if (place.top === 0) return place;
  for (const anchor of scroller.querySelectorAll<HTMLElement>(
    '[data-reader-anchor]',
  )) {
    const box = anchor.getBoundingClientRect();
    if (!box.height || box.bottom <= top) continue;
    const paragraphs = Array.from(anchor.querySelectorAll('p'));
    const paragraph = paragraphs.findIndex(
      (item) => item.getBoundingClientRect().bottom > top,
    );
    const line =
      paragraph < 0 ? box : paragraphs[paragraph].getBoundingClientRect();
    return {
      ...place,
      anchor: anchor.dataset.readerAnchor,
      paragraph,
      fraction:
        line.top < top && line.height
          ? Math.min(1, (top - line.top) / line.height)
          : 0,
      gap: Math.max(0, line.top - top),
    };
  }
  return place;
}

export function restoreText(scroller: HTMLElement, place: TextPlace) {
  const anchor =
    place.anchor &&
    Array.from(
      scroller.querySelectorAll<HTMLElement>('[data-reader-anchor]'),
    ).find((item) => item.dataset.readerAnchor === place.anchor);
  if (!anchor) {
    scroller.scrollTop = place.top;
    return;
  }
  const paragraph =
    place.paragraph !== undefined && place.paragraph >= 0
      ? anchor.querySelectorAll('p')[place.paragraph]
      : undefined;
  const box = (paragraph ?? anchor).getBoundingClientRect();
  scroller.scrollTop +=
    box.top -
    scroller.getBoundingClientRect().top +
    box.height * (place.fraction ?? 0) -
    (place.gap ?? 0);
}

function readTextPlace(key: string): TextPlace {
  const value = readObject(key);
  if (!value || typeof value.top !== 'number' || !Number.isFinite(value.top))
    return { top: 0 };
  return {
    top: Math.max(0, value.top),
    anchor: typeof value.anchor === 'string' ? value.anchor : undefined,
    paragraph:
      typeof value.paragraph === 'number' ? value.paragraph : undefined,
    fraction: typeof value.fraction === 'number' ? value.fraction : 0,
    gap: typeof value.gap === 'number' ? value.gap : 0,
  };
}

export function useReadingScroll(
  courseId: string,
  moduleId: string | undefined,
  linkedMove: string | null,
  layoutReady: boolean,
) {
  const ref = useRef<HTMLDivElement>(null);
  const pendingScroll = useRef<{ key: string; place: TextPlace }>();
  useLayoutEffect(() => {
    const scroller = ref.current;
    if (!scroller || !moduleId) return;
    const key = `${courseKey(courseId)}.text.${moduleId}`;
    const previous = pendingScroll.current;
    pendingScroll.current = undefined;
    let place: TextPlace =
      previous?.key === key
        ? previous.place
        : linkedMove
          ? { top: 0, anchor: linkedMove }
          : readTextPlace(key);
    let receivedInput = false;
    let manuallyScrolled = false;
    function startInput() {
      receivedInput = true;
    }
    let width = -1;
    let restoredTop: number | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;

    function resize() {
      if (!scroller || width === scroller.clientWidth) return;
      width = scroller.clientWidth;
      // A hidden tab has no geometry. Restore after it is visible again.
      if (width > 0 && (layoutReady || manuallyScrolled)) {
        restoreText(scroller, place);
        restoredTop = scroller.scrollTop;
      }
    }
    function saveScroll() {
      // The text is readable while citation metadata is loading. A user who
      // scrolls during that interval chooses a newer place than the bookmark.
      if (!layoutReady && !receivedInput) return;
      if (!scroller || width === 0 || scroller.clientWidth !== width) return;
      const top = scroller.scrollTop;
      // Resizing can generate a scroll event even without user input.
      if (top === restoredTop) return;
      restoredTop = undefined;
      manuallyScrolled = true;
      // Keep scrolling cheap in books with thousands of moves. Find the
      // semantic anchor once the scroll settles, with a pixel fallback meanwhile.
      place = { top };
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (
          width > 0 &&
          scroller.clientWidth === width &&
          scroller.scrollTop === top
        ) {
          place = captureText(scroller);
        }
        writeObject(key, place);
      }, 140);
    }
    function flush() {
      clearTimeout(timer);
      if (!layoutReady) {
        if (!manuallyScrolled) return;
        pendingScroll.current = { key, place };
      }
      writeObject(key, place);
    }
    const intents = ['wheel', 'touchmove', 'pointerdown', 'keydown'];
    if (!layoutReady) {
      for (const event of intents)
        scroller.addEventListener(event, startInput, {
          passive: true,
          once: true,
        });
    }
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(scroller);
    scroller.addEventListener('scroll', saveScroll, { passive: true });
    window.addEventListener('pagehide', flush);
    return () => {
      flush();
      observer.disconnect();
      for (const event of intents)
        scroller.removeEventListener(event, startInput);
      scroller.removeEventListener('scroll', saveScroll);
      window.removeEventListener('pagehide', flush);
    };
  }, [courseId, moduleId, linkedMove, layoutReady]);
  return ref;
}
