import { useState } from 'react';

export function NoteExcerpt({
  text,
  previewLength = 160,
}: {
  text: string;
  previewLength?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const snippet = text
    .slice(0, previewLength)
    .split('\n')
    .slice(0, 3)
    .join('\n');
  if (snippet === text) return <p className="nb-summary">{text}</p>;
  return (
    <div className="nb-excerpt">
      <p className="nb-summary">{expanded ? text : snippet + '…'}</p>
      <button
        type="button"
        className="nb-text-button"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? '收起全文' : '展开全文'}
      </button>
    </div>
  );
}
