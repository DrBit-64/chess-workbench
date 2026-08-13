import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SWRConfig } from 'swr';
import { describe, expect, it, vi } from 'vitest';

import type { PdfExtraction } from '../logic/api/types';

import { CourseCatalog } from './CourseCatalog';
import { Dashboard } from './Dashboard';
import { SourcesPage } from './SourcesPage';

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

function renderPage(node: React.ReactNode) {
  return render(
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      <MemoryRouter>{node}</MemoryRouter>
    </SWRConfig>,
  );
}

const course = {
  id: 'course-1',
  title: '西西里防御',
  description: '从开放西西里开始',
  mode: 'traditional',
  status: 'draft',
  tags: ['黑方'],
  version: 1,
  archived_at: null,
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
};

const source = {
  id: 'source-1',
  kind: 'book',
  title: 'My System',
  author: 'Nimzowitsch',
  publication_date: null,
  external_url: 'https://example.test/book',
  description: null,
  metadata: {},
  version: 1,
  archived_at: null,
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
};

const pdfAsset = {
  id: 'asset-1',
  content_sha256: 'a'.repeat(64),
  byte_size: 1024,
  page_count: 400,
  source_id: 'source-1',
  source_version_id: 'source-version-1',
  source_file_id: 'source-file-1',
  filename: 'opening.pdf',
  title: 'My Opening Book',
  author: null,
  edition: null,
  created_at: '2026-08-09T00:00:00Z',
};

const pdfAsset2 = {
  ...pdfAsset,
  id: 'asset-2',
  filename: 'endgame.pdf',
  title: 'Endgame Manual',
  page_count: 350,
};

const baseJob = {
  id: 'job-1',
  kind: 'pdf_extraction',
  status: 'queued',
  payload: {},
  result: null,
  attempt_count: 0,
  max_attempts: 3,
  cancel_requested_at: null,
  last_error_code: null,
  last_error_message: null,
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
};

const extractionRun = (overrides: Record<string, unknown> = {}) => ({
  id: 'run-1',
  pdf_asset_id: 'asset-1',
  first_page: 319,
  last_page: 399,
  pipeline_version: 'pdf-extraction:v1',
  profile: {},
  has_conflicts: false,
  created_at: '2026-08-09T00:00:00Z',
  job: { ...baseJob },
  ...overrides,
});

const candidate: NonNullable<PdfExtraction['candidate']> = {
  status: 'committed',
  item_count: 5,
  move_node_count: 12,
  figure_count: 1,
  unresolved_item_count: 2,
  warning_count: 3,
  error_count: 0,
  invalid_move_count: 2,
  ambiguous_move_count: 1,
  has_conflicts: true,
  request_sha256: 'c'.repeat(64),
  response_sha256: 'd'.repeat(64),
  provider_response_sha256: 'e'.repeat(64),
  raw_ccef_sha256: 'f'.repeat(64),
  normalized_ccef_sha256: '0'.repeat(64),
};

describe('Stage 4A workbench pages', () => {
  it('renders real dashboard statistics and recent-course navigation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/dashboard/summary') {
          return json({
            course_count: 2,
            module_count: 3,
            source_count: 4,
            knowledge_note_count: 5,
            recent_courses: [course],
          });
        }
        return json({
          status: 'ok',
          service: 'chess-workbench-api',
          version: '0.1.0',
          database: 'ok',
        });
      }),
    );

    renderPage(<Dashboard />);

    expect(await screen.findByText('西西里防御')).toBeTruthy();
    expect(screen.getByText('5')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: /西西里防御/ }).getAttribute('href'),
    ).toBe('/learn/course-1');
  });

  it('shows dashboard API errors without replacing the shell', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        String(input) === '/api/dashboard/summary'
          ? json({}, 503)
          : json({}, 503),
      ),
    );

    renderPage(<Dashboard />);

    expect(await screen.findByText('无法读取工作台统计')).toBeTruthy();
    expect(
      screen.getByRole('heading', { name: '你的棋局知识工作台' }),
    ).toBeTruthy();
  });

  it('queries, filters, and creates courses through the API', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') return json(course, 201);
      return json([course]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<CourseCatalog />);

    expect(await screen.findByText('西西里防御')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('搜索课程'), {
      target: { value: '龙式' },
    });
    fireEvent.keyDown(screen.getByLabelText('搜索课程'), {
      key: 'Enter',
      code: 'Enter',
    });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('q=%E9%BE%99%E5%BC%8F'),
        expect.anything(),
      ),
    );

    fireEvent.click(screen.getByRole('button', { name: '新建课程' }));
    fireEvent.change(await screen.findByLabelText('课程名称'), {
      target: { value: '法兰西防御' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/courses',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ title: '法兰西防御', mode: 'traditional' }),
        }),
      ),
    );
  });

  it('renders an empty course result explicitly', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => json([])),
    );
    renderPage(<CourseCatalog />);
    expect(await screen.findByText('没有匹配的课程')).toBeTruthy();
  });

  it('queries and creates manual sources', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST') return json(source, 201);
      if (url === '/api/pdf-assets') return json({ items: [] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: [] });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('My System')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: '打开原始链接' }).getAttribute('href'),
    ).toBe('https://example.test/book');
    fireEvent.change(screen.getByLabelText('搜索资料'), {
      target: { value: '体系' },
    });
    fireEvent.keyDown(screen.getByLabelText('搜索资料'), {
      key: 'Enter',
      code: 'Enter',
    });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('q=%E4%BD%93%E7%B3%BB'),
        expect.anything(),
      ),
    );

    fireEvent.click(screen.getByRole('button', { name: '添加手工来源' }));
    fireEvent.change(await screen.findByLabelText('标题'), {
      target: { value: '我的课堂笔记' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^添\s*加$/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/citable-sources',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ kind: 'manual', title: '我的课堂笔记' }),
        }),
      ),
    );
  });

  it('shows an explicit empty source state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/pdf-assets') return json({ items: [] });
        if (url.startsWith('/api/pdf-extractions')) return json({ items: [] });
        return json([]);
      }),
    );
    renderPage(<SourcesPage />);
    expect(await screen.findByText('还没有资料')).toBeTruthy();
  });

  it('renders the PDF book-recognition card with assets and real job states', async () => {
    const runs = [
      extractionRun({
        id: 'run-1',
        pdf_asset_id: 'asset-1',
        first_page: 319,
        last_page: 399,
        has_conflicts: false,
      }),
      extractionRun({
        id: 'run-2',
        pdf_asset_id: 'asset-2',
        first_page: 1,
        last_page: 350,
        has_conflicts: true,
        job: {
          ...baseJob,
          id: 'job-2',
          status: 'failed',
          last_error_message: 'OCR 服务不可用',
        },
      }),
      extractionRun({
        id: 'run-3',
        pdf_asset_id: 'missing-asset',
        first_page: 1,
        last_page: 10,
        job: { ...baseJob, id: 'job-3', status: 'succeeded' },
      }),
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets')
        return json({ items: [pdfAsset, pdfAsset2] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('AI 棋书识别')).toBeTruthy();
    expect(screen.getByLabelText('PDF 文件')).toBeTruthy();
    expect(screen.getByLabelText('选择 PDF')).toBeTruthy();
    expect(screen.getByRole('button', { name: '上传 PDF' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '创建识别任务' })).toBeTruthy();

    expect(await screen.findByText('My Opening Book')).toBeTruthy();
    expect(screen.getByText('Endgame Manual')).toBeTruthy();
    expect(screen.getByText('missing-asset')).toBeTruthy();
    expect(screen.getByText('第 319–399 页')).toBeTruthy();
    expect(screen.getByText('排队中')).toBeTruthy();
    expect(screen.getByText('已失败')).toBeTruthy();
    expect(screen.getByText('已完成')).toBeTruthy();
    expect(screen.getByText('有冲突')).toBeTruthy();
    expect(screen.getAllByText('无冲突').length).toBe(2);
    expect(screen.getByText('OCR 服务不可用')).toBeTruthy();
    expect(
      screen.getByText('本页面仅展示后端任务的真实状态，不估算识别进度。'),
    ).toBeTruthy();
    expect(screen.getByText('My System')).toBeTruthy();
  });

  it('uploads a PDF file with trimmed metadata and refreshes asset data', async () => {
    let uploaded = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url === '/api/pdf-assets') {
        uploaded = true;
        return json({ replayed: false, asset: pdfAsset });
      }
      if (url === '/api/pdf-assets') {
        return json({ items: uploaded ? [pdfAsset] : [] });
      }
      if (url.startsWith('/api/pdf-extractions')) return json({ items: [] });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    const file = new File(['%PDF-1.4'], 'opening.pdf', {
      type: 'application/pdf',
    });
    fireEvent.change(screen.getByLabelText('PDF 文件'), {
      target: { files: [file] },
    });
    fireEvent.change(screen.getByLabelText('标题（可选）'), {
      target: { value: '  棋书标题  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传 PDF' }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => url === '/api/pdf-assets' && init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const post = fetchMock.mock.calls.find(
      ([, init]) => init?.method === 'POST',
    );
    const body = post?.[1]?.body as FormData;
    expect(body.get('file')).toBe(file);
    expect(body.get('metadata')).toBe('{"title":"棋书标题"}');

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([url, init]) => url === '/api/pdf-assets' && !init?.method,
        ).length,
      ).toBeGreaterThanOrEqual(2),
    );
    expect(await screen.findByText('My Opening Book（400 页）')).toBeTruthy();
  });

  it('creates an extraction run for physical pages 319..399 of a selected PDF', async () => {
    let created = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url === '/api/pdf-extractions') {
        created = true;
        return json({ replayed: false, extraction: extractionRun() }, 202);
      }
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) {
        return json({ items: created ? [extractionRun()] : [] });
      }
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    fireEvent.mouseDown(await screen.findByLabelText('选择 PDF'));
    fireEvent.click(await screen.findByText('My Opening Book（400 页）'));
    fireEvent.change(screen.getByLabelText('起始物理页'), {
      target: { value: '319' },
    });
    fireEvent.change(screen.getByLabelText('结束物理页'), {
      target: { value: '399' },
    });
    fireEvent.click(
      await screen.findByRole('button', { name: '创建识别任务' }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/pdf-extractions',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            pdf_asset_id: 'asset-1',
            first_page: 319,
            last_page: 399,
          }),
        }),
      ),
    );
    expect(await screen.findByText('排队中')).toBeTruthy();
  });

  it('requests the expected URLs when status and conflict filters change', async () => {
    const runs = [
      extractionRun({
        id: 'run-1',
        first_page: 1,
        last_page: 100,
        job: { ...baseJob, id: 'job-1', status: 'succeeded' },
      }),
      extractionRun({
        id: 'run-2',
        first_page: 1,
        last_page: 50,
        job: { ...baseJob, id: 'job-2', status: 'cancelled' },
      }),
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('已完成')).toBeTruthy();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/pdf-extractions',
        expect.anything(),
      ),
    );

    fireEvent.mouseDown(screen.getByLabelText('任务状态'));
    fireEvent.click(await screen.findByText('排队中'));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('status=queued'),
        expect.anything(),
      ),
    );

    fireEvent.mouseDown(screen.getByLabelText('冲突状态'));
    fireEvent.click(await screen.findByText('有冲突'));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('has_conflicts=true'),
        expect.anything(),
      ),
    );

    fireEvent.mouseDown(screen.getByLabelText('任务状态'));
    fireEvent.click(await screen.findByText('全部状态'));
    fireEvent.mouseDown(screen.getByLabelText('冲突状态'));
    fireEvent.click(await screen.findByText('全部冲突'));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/pdf-extractions',
        expect.anything(),
      ),
    );
  });

  it('labels invalid ranges before posting an extraction request', async () => {
    let postRequested = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST') postRequested = true;
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: [] });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    fireEvent.click(
      await screen.findByRole('button', { name: '创建识别任务' }),
    );
    expect(await screen.findByText('请先选择 PDF 资料')).toBeTruthy();

    fireEvent.mouseDown(await screen.findByLabelText('选择 PDF'));
    fireEvent.click(await screen.findByText('My Opening Book（400 页）'));
    fireEvent.change(screen.getByLabelText('起始物理页'), {
      target: { value: '399' },
    });
    fireEvent.change(screen.getByLabelText('结束物理页'), {
      target: { value: '319' },
    });
    fireEvent.click(screen.getByRole('button', { name: '创建识别任务' }));
    expect(
      await screen.findByText('结束物理页不能小于起始物理页'),
    ).toBeTruthy();

    expect(postRequested).toBe(false);
  });

  it('shows explicit empty states for PDF assets and runs', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/pdf-assets') return json({ items: [] });
        if (url.startsWith('/api/pdf-extractions')) return json({ items: [] });
        return json([]);
      }),
    );
    renderPage(<SourcesPage />);

    expect(await screen.findByText('还没有 PDF 资料')).toBeTruthy();
    expect(screen.getByText('还没有识别任务')).toBeTruthy();
    expect(
      screen.getByText('本页面仅展示后端任务的真实状态，不估算识别进度。'),
    ).toBeTruthy();
    expect(screen.getByText('还没有资料')).toBeTruthy();
  });

  it('shows the committed evidence summary with shortened manifest hashes', async () => {
    const runs = [
      extractionRun({
        id: 'run-1',
        first_page: 319,
        last_page: 399,
        job: { ...baseJob, id: 'job-1', status: 'succeeded' },
        evidence: {
          status: 'committed',
          page_count: 5,
          fragment_count: 12,
          warning_count: 1,
          render_manifest_sha256: 'a'.repeat(64),
          ocr_manifest_sha256: 'b'.repeat(64),
        },
      }),
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(
      await screen.findByText('已提交证据：5 页 · 12 个文本片段 · 1 个警告'),
    ).toBeTruthy();
    expect(screen.getByText('Manifest 已提交')).toBeTruthy();
    expect(screen.getByText(`渲染 ${'a'.repeat(12)}…`)).toBeTruthy();
    expect(screen.getByText(`OCR ${'b'.repeat(12)}…`)).toBeTruthy();
    // The summary uses the committed evidence counts, never the requested range.
    expect(screen.queryByText(/已提交证据：81 页/)).toBeNull();
  });

  it('warns when a succeeded run has no committed evidence', async () => {
    const runs = [
      extractionRun({
        id: 'run-1',
        job: { ...baseJob, id: 'job-1', status: 'succeeded' },
        evidence: null,
      }),
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('证据索引尚未完整提交')).toBeTruthy();
    expect(screen.queryByText(/已提交证据：/)).toBeNull();
    expect(screen.queryByText('Manifest 已提交')).toBeNull();
  });

  it('does not claim evidence completion for queued or failed runs', async () => {
    const runs = [
      extractionRun({
        id: 'run-1',
        job: { ...baseJob, id: 'job-1', status: 'queued' },
      }),
      extractionRun({
        id: 'run-2',
        job: {
          ...baseJob,
          id: 'job-2',
          status: 'failed',
          last_error_message: 'OCR 服务不可用',
        },
      }),
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('排队中')).toBeTruthy();
    expect(screen.getByText('已失败')).toBeTruthy();
    expect(screen.getByText('OCR 服务不可用')).toBeTruthy();
    expect(screen.queryByText(/已提交证据：/)).toBeNull();
    expect(screen.queryByText('Manifest 已提交')).toBeNull();
    expect(screen.queryByText('证据索引尚未完整提交')).toBeNull();
  });

  it('renders the committed Stage 8C candidate summary with short hashes', async () => {
    const runs = [
      extractionRun({
        id: 'run-1',
        pipeline_version: 'pdf-extraction:v2',
        has_conflicts: true,
        job: {
          ...baseJob,
          id: 'job-1',
          status: 'succeeded',
          last_error_message: '上一次模型输出不是合法 JSON',
        },
        candidate,
      }),
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('已生成 CCEF 候选')).toBeTruthy();
    expect(
      screen.getByText(
        '内容项 5 · 棋步 12 · 未解决 2 · 警告 3 · 错误 0 · 非法棋步 2 · 歧义棋步 1',
      ),
    ).toBeTruthy();
    expect(screen.getByText(`原始 CCEF ${'f'.repeat(12)}…`)).toBeTruthy();
    expect(screen.getByText(`规范 CCEF ${'0'.repeat(12)}…`)).toBeTruthy();
    expect(screen.queryByText('上一次模型输出不是合法 JSON')).toBeNull();

    // The review entry link stays available even when the run has conflicts.
    expect(
      screen.getByRole('link', { name: '打开审核页面' }).getAttribute('href'),
    ).toBe('/sources/pdf-extractions/run-1/review');
    expect(screen.getByText('有冲突')).toBeTruthy();
  });

  it('uses only run.has_conflicts for the conflict tag, not the candidate summary', async () => {
    const runs = [
      extractionRun({
        id: 'run-1',
        pipeline_version: 'pdf-extraction:v2',
        has_conflicts: false,
        job: { ...baseJob, id: 'job-1', status: 'succeeded' },
        candidate: { ...candidate, has_conflicts: true },
      }),
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('已生成 CCEF 候选')).toBeTruthy();
    expect(screen.getByText('无冲突')).toBeTruthy();
    expect(screen.queryByText('有冲突')).toBeNull();

    // The review entry link remains available with has_conflicts=false.
    expect(
      screen.getByRole('link', { name: '打开审核页面' }).getAttribute('href'),
    ).toBe('/sources/pdf-extractions/run-1/review');
  });

  it('warns when a succeeded v2 run has no committed candidate', async () => {
    const runs = [
      extractionRun({
        id: 'run-1',
        pipeline_version: 'pdf-extraction:v2',
        job: { ...baseJob, id: 'job-1', status: 'succeeded' },
        candidate: null,
      }),
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('候选索引尚未完整提交')).toBeTruthy();
    expect(screen.queryByText('已生成 CCEF 候选')).toBeNull();
    expect(screen.queryByRole('link', { name: '打开审核页面' })).toBeNull();
  });

  it('does not warn for a historical v1 run without a candidate', async () => {
    const runs = [
      extractionRun({
        id: 'run-1',
        pipeline_version: 'pdf-extraction:v1',
        job: { ...baseJob, id: 'job-1', status: 'succeeded' },
        candidate: null,
      }),
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('已完成')).toBeTruthy();
    expect(screen.queryByText('候选索引尚未完整提交')).toBeNull();
    expect(screen.queryByText('已生成 CCEF 候选')).toBeNull();
    expect(screen.queryByRole('link', { name: '打开审核页面' })).toBeNull();
  });

  it('never shows the review link for queued, running, failed, or cancelled runs', async () => {
    const runs = ['queued', 'running', 'failed', 'cancelled'].map(
      (status, index) =>
        extractionRun({
          id: `run-${index}`,
          pipeline_version: 'pdf-extraction:v2',
          job: { ...baseJob, id: `job-${index}`, status },
          candidate: null,
        }),
    );
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('排队中')).toBeTruthy();
    expect(screen.queryByRole('link', { name: '打开审核页面' })).toBeNull();
  });

  it('never renders full hashes, paths, or raw candidate content', async () => {
    const runs = [
      extractionRun({
        id: 'run-1',
        pipeline_version: 'pdf-extraction:v2',
        job: { ...baseJob, id: 'job-1', status: 'succeeded' },
        candidate,
      }),
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/pdf-assets') return json({ items: [pdfAsset] });
      if (url.startsWith('/api/pdf-extractions')) return json({ items: runs });
      return json([source]);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(<SourcesPage />);

    expect(await screen.findByText('已生成 CCEF 候选')).toBeTruthy();
    expect(screen.queryByText('f'.repeat(64))).toBeNull();
    expect(screen.queryByText('0'.repeat(64))).toBeNull();
    expect(screen.queryByText(/\/api\/pdf-extractions/)).toBeNull();
    expect(screen.queryByText(/secret|api[_-]?key/i)).toBeNull();
  });
});
