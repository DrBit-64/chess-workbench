import { describe, expect, it } from 'vitest';

const MEASURE_PROPS = [
  'padding-top',
  'padding-bottom',
  'border-top-width',
  'border-bottom-width',
];

describe('textarea computed-style measurement contract', () => {
  it('returns finite pixel values for the four parseFloat-measured props', () => {
    const textarea = document.createElement('textarea');
    document.body.appendChild(textarea);
    try {
      const style = window.getComputedStyle(textarea);
      for (const prop of MEASURE_PROPS) {
        const value = style.getPropertyValue(prop);
        expect(
          Number.isFinite(Number.parseFloat(value)),
          `${prop} was ${JSON.stringify(value)}`,
        ).toBe(true);
      }
    } finally {
      document.body.removeChild(textarea);
    }
  });

  it('leaves non-textarea computed styles untouched', () => {
    const div = document.createElement('div');
    div.style.paddingTop = '7px';
    document.body.appendChild(div);
    try {
      const style = window.getComputedStyle(div);
      expect(style.getPropertyValue('padding-top')).toBe('7px');
    } finally {
      document.body.removeChild(div);
    }
  });
});
