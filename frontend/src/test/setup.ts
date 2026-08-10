import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

class ResizeObserverStub implements ResizeObserver {
  disconnect() {}
  observe() {}
  unobserve() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverStub);

const originalGetComputedStyle = window.getComputedStyle.bind(window);

// @rc-component/input's calculateNodeHeight parses these four textarea
// computed-style values with parseFloat.  jsdom leaves some of them as
// '' which parseFloat turns into NaN; guard them with a finite 0px
// fallback so the measurement contract stays deterministic.
const TEXTAREA_MEASURE_PROPS = new Set([
  'padding-top',
  'padding-bottom',
  'border-top-width',
  'border-bottom-width',
]);

function finitePxValue(value: string): string {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? value : '0px';
}

window.getComputedStyle = (element: Element) => {
  const style = originalGetComputedStyle(element);
  if (!(element instanceof HTMLTextAreaElement)) {
    return style;
  }
  return new Proxy(style, {
    get(target, prop) {
      if (prop === 'getPropertyValue') {
        return (property: string) => {
          const value = target.getPropertyValue(property);
          return TEXTAREA_MEASURE_PROPS.has(property)
            ? finitePxValue(value)
            : value;
        };
      }
      const value = Reflect.get(target, prop);
      return typeof value === 'function' ? value.bind(target) : value;
    },
  });
};
