import { Alert, Card, Empty, Spin, Typography } from 'antd';
import { Link, useParams } from 'react-router-dom';
import useSWR from 'swr';

import { fetchJson } from '../logic/api/client';
import type { PdfSourceEvidence } from '../logic/api/types';

type SourceFragment = PdfSourceEvidence['pages'][number]['fragments'][number];

const ROLE_LABELS: Record<string, string> = {
  mainline: '实战主谱',
  variation: '变化',
  example: '示例',
  plan: '计划',
  annotation: '注释',
  mention: '提及',
};

function sourceTarget(ref: string): { href: string; label: string } | null {
  const match = /^s(\d+)_(\d+)$/.exec(ref);
  if (!match) return null;
  return {
    href: `#source-${ref}`,
    label: `第 ${match[1]} 页 · 第 ${Number(match[2]) + 1} 段`,
  };
}

function StyledFragment({ fragment }: { fragment: SourceFragment }) {
  const styleRuns = fragment.style_runs ?? [];
  if (styleRuns.length === 0) {
    return <>{fragment.text}</>;
  }
  const pieces: React.ReactNode[] = [];
  let cursor = 0;
  styleRuns.forEach((run, index) => {
    if (cursor < run.start) {
      pieces.push(fragment.text.slice(cursor, run.start));
    }
    pieces.push(
      <span
        key={`${fragment.order}-${index}`}
        style={{
          color: run.color ?? undefined,
          fontWeight: run.bold ? 700 : undefined,
        }}
      >
        {fragment.text.slice(run.start, run.end)}
      </span>,
    );
    cursor = run.end;
  });
  if (cursor < fragment.text.length) {
    pieces.push(fragment.text.slice(cursor));
  }
  return <>{pieces}</>;
}

export function PdfSourcePage() {
  const { runId } = useParams<{ runId: string }>();
  const sourceUrl = runId
    ? `/api/pdf-extractions/${encodeURIComponent(runId)}/source`
    : null;
  const { data, error, isLoading } = useSWR<PdfSourceEvidence>(
    sourceUrl,
    fetchJson,
  );

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 flex items-baseline gap-4">
        <h1 className="text-2xl font-semibold">PDF 原文证据</h1>
        <Link to="/sources">← 返回资料</Link>
        {runId ? (
          <Link
            to={`/sources/pdf-extractions/${encodeURIComponent(runId)}/review`}
          >
            打开审核
          </Link>
        ) : null}
      </div>
      <Typography.Paragraph type="secondary">
        这里显示已保存的页面图像和按阅读顺序排列的原文片段；候选提取失败时仍可查看。
      </Typography.Paragraph>
      {isLoading ? <Spin /> : null}
      {data?.evidence_status === 'unavailable' ? (
        <Alert
          type="warning"
          className="mb-4"
          message="原文识别尚不可用"
          description={`失败原因：${data.error_code ?? 'unknown'}。仍可查看原始 PDF 页图。`}
        />
      ) : null}
      {error ? (
        <Alert
          type="warning"
          message="来源证据尚不可用"
          description={String(error)}
        />
      ) : null}
      {data && data.pages.length === 0 ? (
        <Empty description="此页段没有已保存的文字片段" />
      ) : null}
      {(data?.reading_hints ?? []).length > 0 ? (
        <section
          aria-label="排版阅读线索"
          className="mb-5 rounded border border-blue-200 bg-blue-50 p-3"
        >
          <h2 className="mb-1 font-semibold">排版阅读线索</h2>
          <p className="mb-2 text-sm text-stone-600">
            这些线索来自当前页段的字体和颜色，棋谱角色仍需结合正文审核。
          </p>
          <ul className="space-y-2 text-sm">
            {(data?.reading_hints ?? []).map((hint, index) => (
              <li key={index}>
                <span>{hint.text}</span>
                <span className="ml-2 inline-flex flex-wrap gap-2">
                  {hint.source_refs.map((ref) => {
                    const target = sourceTarget(ref);
                    return target ? (
                      <a
                        key={ref}
                        href={target.href}
                        className="text-blue-800 underline"
                      >
                        {target.label}
                      </a>
                    ) : null;
                  })}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <div className="grid gap-6">
        {data?.pages.map((page) => (
          <Card key={page.physical_page} title={`物理页 ${page.physical_page}`}>
            <div className="grid gap-4 lg:grid-cols-2">
              <img
                src={`/api/pdf-extractions/${encodeURIComponent(data.run_id)}/source/pages/${page.physical_page}`}
                alt={`PDF 物理页 ${page.physical_page}`}
                className="max-h-[75vh] w-full object-contain object-top"
              />
              <ol className="max-h-[75vh] space-y-2 overflow-auto pl-6">
                {page.fragments.map((fragment) => (
                  <li
                    key={`${fragment.order}-${fragment.fragment_sha256}`}
                    id={`source-s${page.physical_page}_${fragment.order}`}
                    className="scroll-mt-4 rounded px-1 target:bg-amber-100"
                  >
                    <p className="whitespace-pre-wrap text-sm">
                      <StyledFragment fragment={fragment} />
                    </p>
                    <div className="flex flex-wrap items-center gap-1 text-xs">
                      <Typography.Text type="secondary" className="text-xs!">
                        {fragment.origin} · 第 {fragment.order + 1} 段
                      </Typography.Text>
                      {(fragment.roles ?? []).map((role) => (
                        <span
                          key={role}
                          className="rounded bg-stone-100 px-1.5 py-0.5 text-stone-700"
                        >
                          {ROLE_LABELS[role] ?? role} · 待审核
                        </span>
                      ))}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          </Card>
        ))}
      </div>
    </main>
  );
}
