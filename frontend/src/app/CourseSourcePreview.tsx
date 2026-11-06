import { useLayoutEffect, useMemo, useRef, useState } from 'react';

import './courseSourcePreview.css';

interface SourcePreview {
  assetId: string;
  page: number;
  title: string;
  contentUrl: string;
}

interface ScanView {
  x: number;
  y: number;
  enlarged: boolean;
}

function savedView(key: string): ScanView {
  try {
    const view = JSON.parse(localStorage.getItem(key) ?? 'null');
    if (
      view &&
      Number.isFinite(view.x) &&
      view.x >= 0 &&
      view.x <= 1 &&
      Number.isFinite(view.y) &&
      view.y >= 0 &&
      view.y <= 1 &&
      typeof view.enlarged === 'boolean'
    )
      return view;
  } catch {
    // Reading still works when storage is unavailable.
  }
  return { x: 0, y: 0, enlarged: false };
}

export function CourseSourcePreview({
  preview,
  moduleId,
  pageIndex,
  pageCount,
  onPage,
}: {
  preview: SourcePreview;
  moduleId: string;
  pageIndex: number;
  pageCount: number;
  onPage: (direction: -1 | 1) => void;
}) {
  const storageKey = `chess-workbench.scan.v1:${moduleId}:${preview.assetId}:${preview.page}`;
  const bookmark = useMemo(() => savedView(storageKey), [storageKey]);
  const viewport = useRef<HTMLDivElement>(null);
  const scan = useRef<HTMLImageElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const expandButton = useRef<HTMLButtonElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [enlarged, setEnlarged] = useState(bookmark.enlarged);
  const [failedUrl, setFailedUrl] = useState<string>();

  useLayoutEffect(() => {
    setEnlarged(bookmark.enlarged);
    const scroller = viewport.current!;
    const image = scan.current!;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let dirty = false;
    const flush = () => {
      clearTimeout(timer);
      if (!dirty) return;
      try {
        localStorage.setItem(storageKey, JSON.stringify(bookmark));
      } catch {
        // Private browsing and a full cache must not interrupt navigation.
      }
      dirty = false;
    };
    // Store a point on the scan, so reflowing or rotating the phone keeps
    // the same part of the printed page in view.
    const restore = () => {
      if (!image.complete || !image.naturalWidth || !scroller.clientWidth)
        return;
      scroller.scrollLeft = bookmark.x * scroller.scrollWidth;
      scroller.scrollTop = bookmark.y * scroller.scrollHeight;
    };
    const remember = () => {
      if (!image.complete || !image.naturalWidth || !scroller.clientWidth)
        return;
      bookmark.x = Math.max(0, scroller.scrollLeft / scroller.scrollWidth);
      bookmark.y = Math.max(0, scroller.scrollTop / scroller.scrollHeight);
      dirty = true;
      clearTimeout(timer);
      timer = setTimeout(flush, 160);
    };
    const observer = new ResizeObserver(restore);
    observer.observe(scroller);
    observer.observe(image);
    image.addEventListener('load', restore);
    scroller.addEventListener('scroll', remember, { passive: true });
    window.addEventListener('pagehide', flush);
    restore();
    return () => {
      observer.disconnect();
      scroller.removeEventListener('scroll', remember);
      image.removeEventListener('load', restore);
      window.removeEventListener('pagehide', flush);
      flush();
    };
  }, [bookmark, storageKey]);

  function toggleZoom() {
    bookmark.enlarged = !enlarged;
    setEnlarged(bookmark.enlarged);
    try {
      localStorage.setItem(storageKey, JSON.stringify(bookmark));
    } catch {
      // Zoom is still available in memory.
    }
  }

  function toggleExpanded() {
    const surface = dialog.current!;
    // The same page element stays mounted while the browser elevates it
    // to a modal. This also traps focus and puts it above sticky page chrome.
    if (typeof surface.showModal === 'function') {
      surface.close();
      if (expanded) surface.show();
      else surface.showModal();
    }
    setExpanded(!expanded);
    expandButton.current?.focus({ preventScroll: true });
  }

  return (
    <dialog
      ref={dialog}
      open
      aria-label="原书扫描页"
      className={`course-source-preview${expanded ? ' is-expanded' : ''}`}
      onCancel={(event) => {
        event.preventDefault();
        if (expanded) toggleExpanded();
      }}
    >
      <div className="scan-tools">
        <button
          type="button"
          aria-label="上一页"
          disabled={pageIndex <= 0}
          onClick={() => onPage(-1)}
        >
          ‹
        </button>
        <span
          className="scan-page-number"
          title={preview.title}
          aria-live="polite"
        >
          第 {preview.page} 页
        </span>
        <button
          type="button"
          aria-label="下一页"
          disabled={pageIndex >= pageCount - 1}
          onClick={() => onPage(1)}
        >
          ›
        </button>
        <span className="scan-source-title" title={preview.title}>
          {preview.title}
        </span>
        <button
          type="button"
          aria-label={enlarged ? '适配栏宽' : '放大扫描页'}
          onClick={toggleZoom}
        >
          {enlarged ? '适宽' : '放大'}
        </button>
        <button
          ref={expandButton}
          type="button"
          aria-pressed={expanded}
          onClick={toggleExpanded}
        >
          {expanded ? '收起全屏' : '全屏'}
        </button>
      </div>
      <div
        ref={viewport}
        className="course-source-scroll"
        role="region"
        aria-label="原书页面滚动区"
        tabIndex={0}
      >
        <img
          ref={scan}
          src={preview.contentUrl}
          alt={`${preview.title} 第 ${preview.page} 页`}
          style={{ width: enlarged ? '200%' : '100%' }}
          hidden={failedUrl === preview.contentUrl}
          onError={() => setFailedUrl(preview.contentUrl)}
          onLoad={() => setFailedUrl(undefined)}
        />
        {failedUrl === preview.contentUrl && (
          <p role="status">本页扫描图暂时无法加载。</p>
        )}
      </div>
    </dialog>
  );
}
