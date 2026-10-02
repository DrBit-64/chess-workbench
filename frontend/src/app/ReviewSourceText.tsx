import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import { type ParagraphCoverage } from './reviewSourceCoverage';
import { useReviewSource } from './reviewSourceContext';

export function CoverageSummary({
  coverage,
}: {
  coverage: ParagraphCoverage | null;
}) {
  if (!coverage) return null;
  if (coverage.unaligned)
    return (
      <span className="text-xs not-italic text-amber-800">
        文字与来源未能精确对应 · 待核对
      </span>
    );
  if (!coverage.mentions.length) return null;
  return (
    <span
      className="mr-2 inline-flex flex-wrap gap-x-2 text-xs not-italic"
      aria-label="正文棋步识别统计"
    >
      <span className="text-emerald-800">已入谱 {coverage.recorded} 招</span>
      {coverage.blocked > 0 && (
        <span className="font-medium text-red-700">
          模型已声明但受阻 {coverage.blocked} 招
        </span>
      )}
      <span
        className={
          coverage.pending ? 'font-medium text-amber-800' : 'text-stone-500'
        }
      >
        待核对 {coverage.pending}
      </span>
      {coverage.plan > 0 && (
        <span className="text-stone-500">计划 {coverage.plan}（未入谱）</span>
      )}
      {coverage.mention > 0 && (
        <span className="text-stone-500">
          引用 {coverage.mention}（未入谱）
        </span>
      )}
    </span>
  );
}

export function ReviewSourceText({
  text,
  textFormat,
  coverage,
}: {
  text: string;
  textFormat?: string | null;
  coverage: ParagraphCoverage | null;
}) {
  const { navigate } = useReviewSource();
  if (textFormat === 'markdown')
    return (
      <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{text}</ReactMarkdown>
    );
  if (!coverage?.mentions.length)
    return <span className="whitespace-pre-wrap">{text}</span>;
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const [number, mention] of coverage.mentions.entries()) {
    parts.push(text.slice(cursor, mention.start));
    const raw = text.slice(mention.start, mention.end);
    if (mention.status === 'recorded' && mention.target) {
      const target = mention.target;
      parts.push(
        <button
          key={number}
          type="button"
          className="rounded-sm underline decoration-emerald-600 decoration-2 underline-offset-4 hover:bg-emerald-50"
          title="已入谱 · 点击定位棋步（不表示挂接已人工确认）"
          aria-label={`${raw}，已入谱，定位棋步`}
          onClick={(event) => {
            event.stopPropagation();
            navigate(target);
          }}
        >
          {raw}
        </button>,
      );
    } else {
      const pending = mention.status === 'pending';
      const blocked = mention.status === 'blocked';
      const label = blocked
        ? '模型已声明为棋步，但没有进入合法棋谱；请检查本节入口与后续变化'
        : pending
          ? '待核对：当前棋谱没有唯一对应节点'
          : `模型判为${mention.status === 'plan' ? '计划' : '引用'}，未入谱；可用段落下方“转为棋步”改判`;
      parts.push(
        <span
          key={number}
          tabIndex={0}
          title={label}
          aria-label={`${raw}，${label}`}
          className={
            blocked
              ? 'rounded-sm bg-red-100 underline decoration-red-600 underline-offset-4'
              : pending
                ? 'rounded-sm bg-amber-100 underline decoration-amber-600 underline-offset-4'
                : 'underline decoration-stone-400 decoration-dotted underline-offset-4'
          }
        >
          {raw}
        </span>,
      );
    }
    cursor = mention.end;
  }
  parts.push(text.slice(cursor));
  return <span className="whitespace-pre-wrap">{parts}</span>;
}
