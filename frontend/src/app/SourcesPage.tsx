import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import { useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import useSWR from 'swr';

import {
  ApiError,
  fetchJson,
  requestFormData,
  requestJson,
} from '../logic/api/client';
import type {
  CitableSource,
  PdfAssetEnvelope,
  PdfAssetListResponse,
  PdfExtraction,
  PdfExtractionEnvelope,
  PdfExtractionListResponse,
  Source,
} from '../logic/api/types';

const kinds = [
  ['manual', '手工笔记'],
  ['web', '网页'],
  ['book', '书籍'],
  ['video', '视频'],
  ['article', '文章'],
  ['pgn', 'PGN'],
  ['game', '对局'],
  ['other', '其他'],
].map(([value, label]) => ({ value, label }));

type RunStatus = PdfExtraction['job']['status'];

const statusOptions: { value: string; label: string }[] = [
  { value: 'all', label: '全部状态' },
  { value: 'queued', label: '排队中' },
  { value: 'running', label: '识别中' },
  { value: 'succeeded', label: '已完成' },
  { value: 'failed', label: '已失败' },
  { value: 'cancelled', label: '已取消' },
];

const conflictOptions = [
  { value: 'all', label: '全部冲突' },
  { value: 'none', label: '无冲突' },
  { value: 'conflict', label: '有冲突' },
];

const statusLabels: Record<RunStatus, string> = {
  queued: '排队中',
  running: '识别中',
  succeeded: '已完成',
  failed: '已失败',
  cancelled: '已取消',
};

const activeStatuses: RunStatus[] = ['queued', 'running'];

export function SourcesPage() {
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState<string>();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [author, setAuthor] = useState('');
  const [edition, setEdition] = useState('');
  const [uploadError, setUploadError] = useState<string>();
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const [assetId, setAssetId] = useState<string>();
  const [firstPage, setFirstPage] = useState<number>();
  const [lastPage, setLastPage] = useState<number>();
  const [runError, setRunError] = useState<string>();
  const [creatingRun, setCreatingRun] = useState(false);

  const [statusFilter, setStatusFilter] = useState('all');
  const [conflictFilter, setConflictFilter] = useState('all');

  const key = useMemo(() => {
    const params = new URLSearchParams();
    if (query.trim()) params.set('q', query.trim());
    if (kind) params.set('kind', kind);
    return `/api/sources${params.size ? `?${params.toString()}` : ''}`;
  }, [kind, query]);

  const runsKey = useMemo(() => {
    const params = new URLSearchParams();
    if (statusFilter !== 'all') params.set('status', statusFilter);
    if (conflictFilter === 'none') params.set('has_conflicts', 'false');
    else if (conflictFilter === 'conflict') params.set('has_conflicts', 'true');
    return `/api/pdf-extractions${params.size ? `?${params.toString()}` : ''}`;
  }, [conflictFilter, statusFilter]);

  const { data: sources = [], mutate } = useSWR<Source[]>(key, fetchJson);
  const { data: assetList, mutate: mutateAssets } =
    useSWR<PdfAssetListResponse>('/api/pdf-assets', fetchJson);
  const { data: runList, mutate: mutateRuns } =
    useSWR<PdfExtractionListResponse>(runsKey, fetchJson, {
      refreshInterval: (latest) =>
        (latest?.items ?? []).some((item) =>
          activeStatuses.includes(item.job.status),
        )
          ? 2000
          : 0,
    });

  const assets = assetList?.items ?? [];
  const runs = runList?.items ?? [];
  const selectedAsset = assets.find((item) => item.id === assetId) ?? null;
  const assetsById = new Map(assets.map((item) => [item.id, item]));

  async function createSource(values: {
    kind: string;
    title: string;
    external_url?: string;
  }) {
    await requestJson<CitableSource>('/api/citable-sources', {
      method: 'POST',
      body: JSON.stringify(values),
    });
    setOpen(false);
    form.resetFields();
    await mutate();
    void message.success('资料已添加');
  }

  async function submitUpload() {
    if (!file) {
      setUploadError('请选择要上传的 PDF 文件');
      return;
    }
    const name = file.name.toLowerCase();
    if (
      !name.endsWith('.pdf') ||
      (file.type !== '' && file.type !== 'application/pdf')
    ) {
      setUploadError('文件名必须以 .pdf 结尾，类型必须为 application/pdf');
      return;
    }
    const metadata: Record<string, string> = {};
    if (title.trim()) metadata.title = title.trim();
    if (author.trim()) metadata.author = author.trim();
    if (edition.trim()) metadata.edition = edition.trim();
    const formData = new FormData();
    formData.append('file', file);
    if (Object.keys(metadata).length > 0) {
      formData.append('metadata', JSON.stringify(metadata));
    }
    try {
      setUploading(true);
      const envelope = await requestFormData<PdfAssetEnvelope>(
        '/api/pdf-assets',
        formData,
      );
      setUploadError(undefined);
      setFile(null);
      if (fileInput.current) fileInput.current.value = '';
      setTitle('');
      setAuthor('');
      setEdition('');
      setAssetId(envelope.asset.id);
      setFirstPage(1);
      setLastPage(envelope.asset.page_count);
      await mutateAssets();
      void message.success(
        envelope.replayed ? 'PDF 内容已存在，已复用原文件' : 'PDF 上传成功',
      );
    } catch (error) {
      setUploadError(
        error instanceof ApiError ? error.message : 'PDF 上传失败，请稍后重试',
      );
    } finally {
      setUploading(false);
    }
  }

  function selectAsset(id: string) {
    setRunError(undefined);
    setAssetId(id);
    const asset = assets.find((item) => item.id === id);
    setFirstPage(asset ? 1 : undefined);
    setLastPage(asset ? asset.page_count : undefined);
  }

  async function submitExtraction() {
    if (!selectedAsset) {
      setRunError('请先选择 PDF 资料');
      return;
    }
    if (
      typeof firstPage !== 'number' ||
      !Number.isInteger(firstPage) ||
      typeof lastPage !== 'number' ||
      !Number.isInteger(lastPage)
    ) {
      setRunError('物理页必须为整数');
      return;
    }
    if (
      firstPage < 1 ||
      lastPage < 1 ||
      firstPage > selectedAsset.page_count ||
      lastPage > selectedAsset.page_count
    ) {
      setRunError(`物理页必须在 1 到 ${selectedAsset.page_count} 之间`);
      return;
    }
    if (lastPage < firstPage) {
      setRunError('结束物理页不能小于起始物理页');
      return;
    }
    try {
      setCreatingRun(true);
      const envelope = await requestJson<PdfExtractionEnvelope>(
        '/api/pdf-extractions',
        {
          method: 'POST',
          body: JSON.stringify({
            pdf_asset_id: selectedAsset.id,
            first_page: firstPage,
            last_page: lastPage,
          }),
        },
      );
      setRunError(undefined);
      await mutateRuns();
      void message.success(
        envelope.replayed ? '识别任务已存在，已复用原任务' : '识别任务已创建',
      );
    } catch (error) {
      setRunError(
        error instanceof ApiError
          ? error.message
          : '创建识别任务失败，请稍后重试',
      );
    } finally {
      setCreatingRun(false);
    }
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <Typography.Title className="mb-1!" level={2}>
            Sources
          </Typography.Title>
          <Typography.Text type="secondary">
            原始资料、版本、文件与可引用片段
          </Typography.Text>
        </div>
        <Button type="primary" onClick={() => setOpen(true)}>
          添加手工来源
        </Button>
      </div>
      <Space className="mb-6" wrap>
        <Input.Search
          aria-label="搜索资料"
          allowClear
          className="w-80"
          placeholder="搜索标题、作者或说明"
          onSearch={setQuery}
        />
        <Select
          aria-label="资料类型"
          allowClear
          className="w-40"
          placeholder="全部类型"
          options={kinds}
          value={kind}
          onChange={setKind}
        />
      </Space>
      <Card className="mb-6" title="AI 棋书识别">
        <div className="grid gap-6 lg:grid-cols-2">
          <Form layout="vertical">
            <Form.Item label="PDF 文件" required>
              <input
                ref={fileInput}
                aria-label="PDF 文件"
                accept=".pdf,application/pdf"
                type="file"
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null);
                  setUploadError(undefined);
                }}
              />
            </Form.Item>
            <Form.Item label="标题（可选）">
              <Input
                aria-label="标题（可选）"
                maxLength={200}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </Form.Item>
            <Form.Item label="作者（可选）">
              <Input
                aria-label="作者（可选）"
                maxLength={200}
                value={author}
                onChange={(event) => setAuthor(event.target.value)}
              />
            </Form.Item>
            <Form.Item label="版本（可选）">
              <Input
                aria-label="版本（可选）"
                maxLength={200}
                value={edition}
                onChange={(event) => setEdition(event.target.value)}
              />
            </Form.Item>
            {uploadError ? (
              <Typography.Paragraph type="danger">
                {uploadError}
              </Typography.Paragraph>
            ) : null}
            <Button
              type="primary"
              loading={uploading}
              disabled={uploading}
              onClick={() => void submitUpload()}
            >
              上传 PDF
            </Button>
          </Form>
          {assets.length ? (
            <Form layout="vertical">
              <Form.Item label="选择 PDF" required>
                <Select
                  aria-label="选择 PDF"
                  placeholder="选择要识别的 PDF"
                  options={assets.map((asset) => ({
                    value: asset.id,
                    label: `${asset.title}（${asset.page_count} 页）`,
                  }))}
                  value={assetId}
                  onChange={selectAsset}
                />
              </Form.Item>
              <Form.Item label="起始物理页">
                <InputNumber
                  aria-label="起始物理页"
                  min={1}
                  max={selectedAsset?.page_count}
                  precision={0}
                  style={{ width: '100%' }}
                  value={firstPage}
                  onChange={(value) => setFirstPage(value ?? undefined)}
                />
              </Form.Item>
              <Form.Item label="结束物理页">
                <InputNumber
                  aria-label="结束物理页"
                  min={1}
                  max={selectedAsset?.page_count}
                  precision={0}
                  style={{ width: '100%' }}
                  value={lastPage}
                  onChange={(value) => setLastPage(value ?? undefined)}
                />
              </Form.Item>
              {runError ? (
                <Typography.Paragraph type="danger">
                  {runError}
                </Typography.Paragraph>
              ) : null}
              <Button
                type="primary"
                loading={creatingRun}
                disabled={creatingRun}
                onClick={() => void submitExtraction()}
              >
                创建识别任务
              </Button>
            </Form>
          ) : (
            <Empty description="还没有 PDF 资料" />
          )}
        </div>
        <Space className="mt-6 w-full" orientation="vertical" size="middle">
          <Space wrap>
            <Select
              aria-label="任务状态"
              options={statusOptions}
              value={statusFilter}
              onChange={setStatusFilter}
            />
            <Select
              aria-label="冲突状态"
              options={conflictOptions}
              value={conflictFilter}
              onChange={setConflictFilter}
            />
            <Typography.Text type="secondary">
              本页面仅展示后端任务的真实状态，不估算识别进度。
            </Typography.Text>
          </Space>
          {runs.length ? (
            <div className="divide-y divide-gray-200" role="list">
              {runs.map((run) => {
                const asset = assetsById.get(run.pdf_asset_id);
                return (
                  <div className="py-3" key={run.id} role="listitem">
                    <div className="flex w-full flex-col gap-1">
                      <div className="flex w-full flex-wrap items-center justify-between gap-2">
                        <Space orientation="vertical" size={0}>
                          <Typography.Text strong>
                            {asset?.title ?? run.pdf_asset_id}
                          </Typography.Text>
                          <Typography.Text type="secondary">
                            第 {run.first_page}–{run.last_page} 页
                          </Typography.Text>
                        </Space>
                        <Space wrap>
                          <Tag>{statusLabels[run.job.status]}</Tag>
                          <Tag
                            color={run.has_conflicts ? 'warning' : 'default'}
                          >
                            {run.has_conflicts ? '有冲突' : '无冲突'}
                          </Tag>
                        </Space>
                      </div>
                      {run.job.status !== 'succeeded' &&
                      run.job.last_error_message ? (
                        <Typography.Text type="danger">
                          {run.job.last_error_message}
                        </Typography.Text>
                      ) : null}
                      {run.evidence ? (
                        <div className="flex flex-col gap-0.5">
                          <Typography.Text>
                            已提交证据：{run.evidence.page_count} 页 ·{' '}
                            {run.evidence.fragment_count} 个文本片段 ·{' '}
                            {run.evidence.warning_count} 个警告
                          </Typography.Text>
                          <div className="flex flex-wrap gap-x-4">
                            <Typography.Text type="secondary">
                              Manifest 已提交
                            </Typography.Text>
                            <Typography.Text type="secondary">
                              渲染{' '}
                              {run.evidence.render_manifest_sha256.slice(0, 12)}
                              …
                            </Typography.Text>
                            <Typography.Text type="secondary">
                              OCR{' '}
                              {run.evidence.ocr_manifest_sha256.slice(0, 12)}…
                            </Typography.Text>
                          </div>
                        </div>
                      ) : run.job.status === 'succeeded' ? (
                        <Typography.Text type="warning">
                          证据索引尚未完整提交
                        </Typography.Text>
                      ) : null}
                      {run.candidate ? (
                        <div className="flex flex-col gap-0.5">
                          <Typography.Text strong>
                            已生成 CCEF 候选
                          </Typography.Text>
                          <Typography.Text>
                            内容项 {run.candidate.item_count} · 棋步{' '}
                            {run.candidate.move_node_count} · 未解决{' '}
                            {run.candidate.unresolved_item_count} · 警告{' '}
                            {run.candidate.warning_count} · 错误{' '}
                            {run.candidate.error_count} · 非法棋步{' '}
                            {run.candidate.invalid_move_count} · 歧义棋步{' '}
                            {run.candidate.ambiguous_move_count}
                          </Typography.Text>
                          <div className="flex flex-wrap gap-x-4">
                            <Typography.Text type="secondary">
                              原始 CCEF{' '}
                              {run.candidate.raw_ccef_sha256.slice(0, 12)}…
                            </Typography.Text>
                            <Typography.Text type="secondary">
                              规范 CCEF{' '}
                              {run.candidate.normalized_ccef_sha256.slice(
                                0,
                                12,
                              )}
                              …
                            </Typography.Text>
                          </div>
                          <Link
                            to={`/sources/pdf-extractions/${encodeURIComponent(
                              run.id,
                            )}/review`}
                            className="text-sm text-blue-600 hover:underline"
                          >
                            打开审核页面
                          </Link>
                        </div>
                      ) : run.pipeline_version === 'pdf-extraction:v2' &&
                        run.job.status === 'succeeded' ? (
                        <Typography.Text type="warning">
                          候选索引尚未完整提交
                        </Typography.Text>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <Empty description="还没有识别任务" />
          )}
        </Space>
      </Card>
      {sources.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {sources.map((source) => (
            <Card key={source.id} title={source.title}>
              <Space orientation="vertical">
                <Tag>
                  {kinds.find((item) => item.value === source.kind)?.label ??
                    source.kind}
                </Tag>
                <Typography.Text type="secondary">
                  {source.author || '未填写作者'}
                </Typography.Text>
                {source.external_url ? (
                  <a
                    href={source.external_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    打开原始链接
                  </a>
                ) : null}
              </Space>
            </Card>
          ))}
        </div>
      ) : (
        <Empty description="还没有资料" />
      )}
      <Modal
        title="添加资料"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        okText="添加"
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ kind: 'manual' }}
          onFinish={(values) =>
            void createSource(
              values as { kind: string; title: string; external_url?: string },
            )
          }
        >
          <Form.Item name="kind" label="类型" rules={[{ required: true }]}>
            <Select
              options={kinds.filter((item) =>
                ['manual', 'web'].includes(item.value),
              )}
            />
          </Form.Item>
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item
            name="external_url"
            label="网页链接"
            rules={[{ type: 'url' }]}
          >
            <Input placeholder="https://" />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}
