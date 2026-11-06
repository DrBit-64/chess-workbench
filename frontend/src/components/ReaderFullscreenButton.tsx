import { message } from 'antd';
import { useEffect, useRef, useState } from 'react';

export function ReaderFullscreenButton() {
  const root = document.documentElement;
  const [active, setActive] = useState(
    () => document.fullscreenElement === root,
  );
  const requested = useRef(false);

  useEffect(() => {
    function sync() {
      const fullscreen = document.fullscreenElement === root;
      setActive(fullscreen);
      if (!fullscreen) requested.current = false;
    }
    document.addEventListener('fullscreenchange', sync);
    return () => {
      document.removeEventListener('fullscreenchange', sync);
      if (requested.current && document.fullscreenElement === root) {
        void document.exitFullscreen().catch(() => {});
      }
    };
  }, [root]);

  if (!document.fullscreenEnabled) return null;

  async function toggle(button: HTMLButtonElement) {
    try {
      if (document.fullscreenElement === root) {
        await document.exitFullscreen();
      } else {
        // Menus and dialogs are portaled to body, so include the entire document.
        requested.current = true;
        await root.requestFullscreen({ navigationUI: 'hide' });
        if (!button.isConnected && document.fullscreenElement === root) {
          await document.exitFullscreen();
        }
      }
    } catch {
      requested.current = document.fullscreenElement === root;
      if (button.isConnected) void message.warning('浏览器未能切换全屏模式');
    }
  }

  const label = active ? '退出全屏' : '全屏阅读';
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={(event) => void toggle(event.currentTarget)}
    >
      <svg
        aria-hidden="true"
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="mx-auto"
      >
        <path
          d={
            active
              ? 'M4 9h5V4m11 5h-5V4M4 15h5v5m11-5h-5v5'
              : 'M4 9V4h5m11 5V4h-5M4 15v5h5m11-5v5h-5'
          }
        />
      </svg>
    </button>
  );
}
