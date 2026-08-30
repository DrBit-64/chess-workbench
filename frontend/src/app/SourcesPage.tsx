import {
  Button,
  Card,
  Descriptions,
  Drawer,
  Dropdown,
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
  requestEmpty,
  requestFormData,
  requestJson,
} from '../logic/api/client';
import type {
  CitableSource,
  PdfAsset,
  PdfAssetEnvelope,
  PdfAssetListResponse,
  PdfExtraction,
  PdfExtractionDocument,
  PdfExtractionDocumentAppendEnvelope,
  PdfExtractionDocumentEnvelope,
  PdfExtractionDocumentListResponse,
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

const statusLabels: Record<RunStatus, string> = {
  queued: '排队中',
  running: '识别中',
  succeeded: '已完成',
  failed: '已失败',
  cancelled: '已取消',
};

const statusColors: Record<RunStatus, string> = {
  queued: 'blue',
  running: 'processing',
  succeeded: 'success',
  failed: 'error',
  cancelled: 'default',
};

const activeStatuses: RunStatus[] = ['queued', 'running'];

function requestKey() {
  return globalThis.crypto.randomUUID();
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function runCanStartDocument(run: PdfExtraction) {
  return run.job.status === 'succeeded' && run.candidate !== null;
}

export function SourcesPage() {
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState<string>();
  const [manualOpen, setManualOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedAssetId, setSelectedAssetId] = useState<string>();
  const [form] = Form.useForm();

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [author, setAuthor] = useState('');
  const [edition, setEdition] = useState('');
  const [uploadError, setUploadError] = useState<string>();
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const [firstPage, setFirstPage] = useState<number>();
  const [lastPage, setLastPage] = useState<number>();
  const [runError, setRunError] = useState<string>();
  const [creatingRun, setCreatingRun] = useState(false);
  const [busyResultId, setBusyResultId] = useState<string>();
  const [appendDocumentId, setAppendDocumentId] = useState<string>();
  const [appendLastPage, setAppendLastPage] = useState<number>();
  const [appendError, setAppendError] = useState<string>();

  const key = useMemo(() => {
    const params = new URLSearchParams();
    if (query.trim()) params.set('q', query.trim());
    if (kind) params.set('kind', kind);
    return `/api/sources${params.size ? `?${params.toString()}` : ''}`;
  }, [kind, query]);

  const { data: sources = [], mutate } = useSWR<Source[]>(key, fetchJson);
  const { data: assetList, mutate: mutateAssets } =
    useSWR<PdfAssetListResponse>('/api/pdf-assets', fetchJson);
  const { data: runList, mutate: mutateRuns } =
    useSWR<PdfExtractionListResponse>('/api/pdf-extractions', fetchJson, {
      refreshInterval: (latest) =>
        (latest?.items ?? []).some((item) =>
          activeStatuses.includes(item.job.status),
        )
          ? 2000
          : 0,
    });
  const { data: documentList, mutate: mutateDocuments } =
    useSWR<PdfExtractionDocumentListResponse>(
      '/api/pdf-extraction-documents',
      fetchJson,
      {
        refreshInterval: (latest) =>
          (latest?.items ?? []).some((document) =>
            document.append_attempts.some((attempt) =>
              activeStatuses.includes(attempt.job.status),
            ),
          )
            ? 2000
            : 0,
      },
    );

  const assets = useMemo(() => assetList?.items ?? [], [assetList]);
  const runs = useMemo(() => runList?.items ?? [], [runList]);
  const documents = useMemo(() => documentList?.items ?? [], [documentList]);
  const selectedAsset =
    assets.find((item) => item.id === selectedAssetId) ?? null;
  const appendDocument =
    documents.find((item) => item.id === appendDocumentId) ?? null;

  const groupedRunIds = useMemo(
    () =>
      new Set(
        documents.flatMap((document) =>
          document.segments.map((segment) => segment.run_id),
        ),
      ),
    [documents],
  );

  const filteredAssets = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return assets;
    return assets.filter((asset) =>
      [asset.title, asset.author, asset.edition, asset.filename]
        .filter((value): value is string => Boolean(value))
        .some((value) => value.toLocaleLowerCase().includes(needle)),
    );
  }, [assets, query]);

  const selectedRuns = useMemo(
    () =>
      runs.filter(
        (run) =>
          run.pdf_asset_id === selectedAssetId && !groupedRunIds.has(run.id),
      ),
    [groupedRunIds, runs, selectedAssetId],
  );
  const selectedDocuments = useMemo(
    () =>
      documents.filter((document) => document.pdf_asset_id === selectedAssetId),
    [documents, selectedAssetId],
  );
  const selectedResults = useMemo(
    () =>
      [
        ...selectedDocuments.map((document) => ({
          kind: 'document' as const,
          createdAt: document.created_at,
          document,
        })),
        ...selectedRuns.map((run) => ({
          kind: 'run' as const,
          createdAt: run.created_at,
          run,
        })),
      ].sort((left, right) => right.createdAt.localeCompare(left.createdAt)),
    [selectedDocuments, selectedRuns],
  );

  const pdfSourceIds = new Set(assets.map((asset) => asset.source_id));
  const otherSources = sources.filter((source) => !pdfSourceIds.has(source.id));

  function resultsForAsset(assetId: string) {
    const documentCount = documents.filter(
      (document) => document.pdf_asset_id === assetId,
    ).length;
    const standaloneCount = runs.filter(
      (run) => run.pdf_asset_id === assetId && !groupedRunIds.has(run.id),
    ).length;
    return documentCount + standaloneCount;
  }

  async function createSource(values: {
    kind: string;
    title: string;
    external_url?: string;
  }) {
    await requestJson<CitableSource>('/api/citable-sources', {
      method: 'POST',
      body: JSON.stringify(values),
    });
    setManualOpen(false);
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
      setUploadOpen(false);
      setSelectedAssetId(envelope.asset.id);
      setFirstPage(1);
      setLastPage(envelope.asset.page_count);
      await mutateAssets();
      void message.success(
        envelope.replayed ? 'PDF 内容已存在，已打开原文件' : 'PDF 上传成功',
      );
    } catch (error) {
      setUploadError(
        error instanceof ApiError ? error.message : 'PDF 上传失败，请稍后重试',
      );
    } finally {
      setUploading(false);
    }
  }

  function openAsset(asset: PdfAsset) {
    setSelectedAssetId(asset.id);
    setFirstPage(1);
    setLastPage(asset.page_count);
    setRunError(undefined);
  }

  async function queueExtraction(
    asset: PdfAsset,
    range: { firstPage: number; lastPage: number },
  ) {
    return requestJson<PdfExtractionEnvelope>('/api/pdf-extractions', {
      method: 'POST',
      headers: { 'Idempotency-Key': requestKey() },
      body: JSON.stringify({
        pdf_asset_id: asset.id,
        first_page: range.firstPage,
        last_page: range.lastPage,
      }),
    });
  }

  async function submitExtraction() {
    if (!selectedAsset) return;
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
      await queueExtraction(selectedAsset, { firstPage, lastPage });
      setRunError(undefined);
      await mutateRuns();
      void message.success('识别任务已创建；相同页段也会保留为独立结果');
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

  async function repeatExtraction(run: PdfExtraction) {
    if (!selectedAsset) return;
    try {
      setBusyResultId(run.id);
      await queueExtraction(selectedAsset, {
        firstPage: run.first_page,
        lastPage: run.last_page,
      });
      await mutateRuns();
      void message.success(
        `已新建第 ${run.first_page}–${run.last_page} 页的独立识别任务`,
      );
    } catch (error) {
      void message.error(
        error instanceof ApiError ? error.message : '重新识别失败',
      );
    } finally {
      setBusyResultId(undefined);
    }
  }

  async function adoptRun(run: PdfExtraction) {
    try {
      setBusyResultId(run.id);
      await requestJson<PdfExtractionDocumentEnvelope>(
        '/api/pdf-extraction-documents',
        {
          method: 'POST',
          body: JSON.stringify({ initial_run_id: run.id }),
        },
      );
      await Promise.all([mutateRuns(), mutateDocuments()]);
      void message.success('该结果已设为连续提取文档');
    } catch (error) {
      void message.error(
        error instanceof ApiError ? error.message : '创建连续提取文档失败',
      );
    } finally {
      setBusyResultId(undefined);
    }
  }

  async function archiveExtraction(
    runId: string,
    status: RunStatus,
    busyId = runId,
  ) {
    const verb =
      status === 'running'
        ? '停止并删除'
        : status === 'queued'
          ? '取消并删除'
          : '删除';
    if (
      !window.confirm(`${verb}这项识别任务？提取记录会被归档，不会物理删除。`)
    ) {
      return;
    }
    try {
      setBusyResultId(busyId);
      await requestEmpty(`/api/pdf-extractions/${encodeURIComponent(runId)}`, {
        method: 'DELETE',
      });
      await Promise.all([mutateRuns(), mutateDocuments()]);
      void message.success(
        status === 'running' ? '已请求停止并从列表移除' : '任务已从列表移除',
      );
    } catch (error) {
      void message.error(
        error instanceof ApiError ? error.message : '删除识别任务失败',
      );
    } finally {
      setBusyResultId(undefined);
    }
  }

  function openAppend(document: PdfExtractionDocument) {
    const nextPage = document.last_page + 1;
    setAppendDocumentId(document.id);
    setAppendLastPage(
      selectedAsset
        ? Math.min(nextPage + 4, selectedAsset.page_count)
        : nextPage,
    );
    setAppendError(undefined);
  }

  async function submitAppend() {
    if (!appendDocument || !selectedAsset) return;
    const nextPage = appendDocument.last_page + 1;
    if (
      typeof appendLastPage !== 'number' ||
      !Number.isInteger(appendLastPage) ||
      appendLastPage < nextPage ||
      appendLastPage > selectedAsset.page_count
    ) {
      setAppendError(
        `结束页必须在 ${nextPage} 到 ${selectedAsset.page_count} 之间`,
      );
      return;
    }
    try {
      setBusyResultId(appendDocument.id);
      await requestJson<PdfExtractionDocumentAppendEnvelope>(
        `/api/pdf-extraction-documents/${encodeURIComponent(
          appendDocument.id,
        )}/appends`,
        {
          method: 'POST',
          headers: { 'Idempotency-Key': requestKey() },
          body: JSON.stringify({
            expected_version: appendDocument.version,
            first_page: nextPage,
            last_page: appendLastPage,
            profile: {},
          }),
        },
      );
      setAppendDocumentId(undefined);
      setAppendError(undefined);
      await Promise.all([mutateRuns(), mutateDocuments()]);
      void message.success('增量提取任务已登记');
    } catch (error) {
      setAppendError(
        error instanceof ApiError ? error.message : '登记增量提取失败',
      );
    } finally {
      setBusyResultId(undefined);
    }
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <Typography.Title className="mb-1!" level={2}>
            资料库
          </Typography.Title>
          <Typography.Text type="secondary">
            一本 PDF 只占一个书籍条目，所有独立或连续提取结果都保存在书籍下面。
          </Typography.Text>
        </div>
        <Space wrap>
          <Button onClick={() => setManualOpen(true)}>添加其他资料</Button>
          <Button type="primary" onClick={() => setUploadOpen(true)}>
            上传 PDF 棋书
          </Button>
        </Space>
      </div>

      <Input.Search
        aria-label="搜索资料"
        allowClear
        className="mb-6 max-w-lg"
        placeholder="搜索书名、作者或文件名"
        onSearch={setQuery}
      />

      <section aria-labelledby="pdf-library-heading" className="mb-10">
        <div className="mb-4 flex items-baseline justify-between gap-4">
          <Typography.Title id="pdf-library-heading" level={3} className="m-0!">
            PDF 棋书
          </Typography.Title>
          <Typography.Text type="secondary">
            {filteredAssets.length} 本
          </Typography.Text>
        </div>
        {filteredAssets.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {filteredAssets.map((asset) => {
              const resultCount = resultsForAsset(asset.id);
              const activeCount = runs.filter(
                (run) =>
                  run.pdf_asset_id === asset.id &&
                  activeStatuses.includes(run.job.status),
              ).length;
              return (
                <Card
                  key={asset.id}
                  title={asset.title}
                  extra={<Tag color="blue">PDF</Tag>}
                  actions={[
                    <Button
                      key="manage"
                      type="link"
                      onClick={() => openAsset(asset)}
                    >
                      管理提取结果
                    </Button>,
                  ]}
                >
                  <Space orientation="vertical" size="small">
                    <Typography.Text>
                      {asset.author || '未填写作者'}
                      {asset.edition ? ` · ${asset.edition}` : ''}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {asset.filename} · {asset.page_count} 页
                    </Typography.Text>
                    <Space wrap>
                      <Tag>{resultCount} 个提取结果</Tag>
                      {activeCount ? (
                        <Tag color="processing">{activeCount} 个处理中</Tag>
                      ) : null}
                    </Space>
                  </Space>
                </Card>
              );
            })}
          </div>
        ) : (
          <Empty description="还没有匹配的 PDF 棋书" />
        )}
      </section>

      <section aria-labelledby="other-sources-heading">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <Typography.Title
            id="other-sources-heading"
            level={3}
            className="m-0!"
          >
            其他资料
          </Typography.Title>
          <Select
            aria-label="资料类型"
            allowClear
            className="w-40"
            placeholder="全部类型"
            options={kinds}
            value={kind}
            onChange={setKind}
          />
        </div>
        {otherSources.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {otherSources.map((source) => (
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
          <Empty description="还没有其他资料" />
        )}
      </section>

      <Drawer
        title={selectedAsset?.title ?? 'PDF 棋书'}
        width={760}
        open={selectedAsset !== null}
        onClose={() => setSelectedAssetId(undefined)}
      >
        {selectedAsset ? (
          <Space className="w-full" orientation="vertical" size="large">
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="作者">
                {selectedAsset.author || '未填写'}
              </Descriptions.Item>
              <Descriptions.Item label="版本">
                {selectedAsset.edition || '未填写'}
              </Descriptions.Item>
              <Descriptions.Item label="文件">
                {selectedAsset.filename}
              </Descriptions.Item>
              <Descriptions.Item label="页数">
                {selectedAsset.page_count}
              </Descriptions.Item>
            </Descriptions>

            <Card size="small" title="新建独立提取">
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
                <Form.Item label="起始物理页" className="mb-0!">
                  <InputNumber
                    aria-label="起始物理页"
                    min={1}
                    max={selectedAsset.page_count}
                    precision={0}
                    className="w-full"
                    value={firstPage}
                    onChange={(value) => setFirstPage(value ?? undefined)}
                  />
                </Form.Item>
                <Form.Item label="结束物理页" className="mb-0!">
                  <InputNumber
                    aria-label="结束物理页"
                    min={1}
                    max={selectedAsset.page_count}
                    precision={0}
                    className="w-full"
                    value={lastPage}
                    onChange={(value) => setLastPage(value ?? undefined)}
                  />
                </Form.Item>
                <Button
                  type="primary"
                  loading={creatingRun}
                  disabled={creatingRun}
                  onClick={() => void submitExtraction()}
                >
                  创建识别任务
                </Button>
              </div>
              {runError ? (
                <Typography.Paragraph type="danger" className="mt-2! mb-0!">
                  {runError}
                </Typography.Paragraph>
              ) : null}
              <Typography.Text type="secondary" className="mt-2 block">
                重复提交相同页段会创建新的独立结果，不会覆盖旧结果。
              </Typography.Text>
            </Card>

            <div>
              <div className="mb-3 flex items-baseline justify-between">
                <Typography.Title level={4} className="m-0!">
                  提取结果
                </Typography.Title>
                <Typography.Text type="secondary">
                  {selectedResults.length} 个
                </Typography.Text>
              </div>
              {selectedResults.length ? (
                <div className="flex flex-col gap-3" role="list">
                  {selectedResults.map((result) => {
                    if (result.kind === 'document') {
                      const document = result.document;
                      const latestAttempt = document.append_attempts.at(-1);
                      const canAppend =
                        document.last_page < selectedAsset.page_count;
                      return (
                        <Card
                          key={`document-${document.id}`}
                          size="small"
                          role="listitem"
                          title={`连续提取 · 第 ${document.first_page}–${document.last_page} 页`}
                          extra={<Tag color="green">v{document.version}</Tag>}
                        >
                          <div className="flex flex-col gap-2">
                            <Typography.Text type="secondary">
                              {document.segments
                                .map(
                                  (segment) =>
                                    `第 ${segment.first_page}–${segment.last_page} 页`,
                                )
                                .join(' → ')}
                            </Typography.Text>
                            {latestAttempt ? (
                              <Space wrap>
                                <Typography.Text>最近增量请求</Typography.Text>
                                <Tag
                                  color={statusColors[latestAttempt.job.status]}
                                >
                                  {statusLabels[latestAttempt.job.status]}
                                </Tag>
                                <Typography.Text type="secondary">
                                  第 {latestAttempt.first_page}–
                                  {latestAttempt.last_page} 页
                                </Typography.Text>
                              </Space>
                            ) : null}
                            <div className="flex items-center justify-between gap-3">
                              <Typography.Text type="secondary">
                                更新于 {formatDate(document.updated_at)}
                              </Typography.Text>
                              <Dropdown
                                trigger={['click']}
                                menu={{
                                  items: [
                                    {
                                      key: 'review',
                                      label: (
                                        <Link
                                          to={`/sources/pdf-extractions/${encodeURIComponent(
                                            document.id,
                                          )}/review`}
                                        >
                                          打开合并审核页面
                                        </Link>
                                      ),
                                    },
                                    {
                                      key: 'append',
                                      label: '继续增量提取',
                                      disabled: !canAppend,
                                    },
                                    {
                                      key: 'edit',
                                      label: '修改（后续接入）',
                                      disabled: true,
                                    },
                                    {
                                      key: 'delete-attempt',
                                      label: latestAttempt
                                        ? `${
                                            latestAttempt.job.status ===
                                            'running'
                                              ? '停止'
                                              : latestAttempt.job.status ===
                                                  'queued'
                                                ? '取消'
                                                : '删除'
                                          }最近提取任务`
                                        : '没有可删除的提取任务',
                                      disabled: !latestAttempt,
                                      danger: true,
                                    },
                                    {
                                      key: 'delete-document',
                                      label: '删除连续文档（后续接入）',
                                      disabled: true,
                                      danger: true,
                                    },
                                  ],
                                  onClick: ({ key }) => {
                                    if (key === 'append') {
                                      openAppend(document);
                                    } else if (
                                      key === 'delete-attempt' &&
                                      latestAttempt
                                    ) {
                                      void archiveExtraction(
                                        latestAttempt.run_id,
                                        latestAttempt.job.status,
                                        document.id,
                                      );
                                    }
                                  },
                                }}
                              >
                                <Button
                                  aria-label="操作"
                                  loading={busyResultId === document.id}
                                >
                                  操作
                                </Button>
                              </Dropdown>
                            </div>
                          </div>
                        </Card>
                      );
                    }

                    const run = result.run;
                    return (
                      <Card
                        key={`run-${run.id}`}
                        size="small"
                        role="listitem"
                        title={`独立提取 · 第 ${run.first_page}–${run.last_page} 页`}
                        extra={
                          <Space wrap>
                            <Tag color={statusColors[run.job.status]}>
                              {statusLabels[run.job.status]}
                            </Tag>
                            {run.candidate ? (
                              <Tag
                                color={
                                  run.has_conflicts ? 'warning' : 'default'
                                }
                              >
                                {run.has_conflicts ? '有冲突' : '无冲突'}
                              </Tag>
                            ) : null}
                          </Space>
                        }
                      >
                        <div className="flex flex-col gap-2">
                          {run.job.status === 'failed' &&
                          run.job.last_error_message ? (
                            <Typography.Text type="danger">
                              {run.job.last_error_message}
                            </Typography.Text>
                          ) : null}
                          {run.candidate ? (
                            <Typography.Text>
                              内容项 {run.candidate.item_count} · 棋步{' '}
                              {run.candidate.move_node_count} · 警告{' '}
                              {run.candidate.warning_count} · 错误{' '}
                              {run.candidate.error_count}
                            </Typography.Text>
                          ) : null}
                          <div className="flex items-center justify-between gap-3">
                            <Typography.Text type="secondary">
                              创建于 {formatDate(run.created_at)}
                            </Typography.Text>
                            <Dropdown
                              trigger={['click']}
                              menu={{
                                items: [
                                  {
                                    key: 'review',
                                    label: run.candidate ? (
                                      <Link
                                        to={`/sources/pdf-extractions/${encodeURIComponent(
                                          run.id,
                                        )}/review`}
                                      >
                                        打开审核页面
                                      </Link>
                                    ) : (
                                      '审核页面尚不可用'
                                    ),
                                    disabled: run.candidate === null,
                                  },
                                  {
                                    key: 'repeat',
                                    label: '重新提取同一页段',
                                  },
                                  {
                                    key: 'adopt',
                                    label: '设为连续提取文档',
                                    disabled: !runCanStartDocument(run),
                                  },
                                  {
                                    key: 'edit',
                                    label: '修改（后续接入）',
                                    disabled: true,
                                  },
                                  {
                                    key: 'delete',
                                    label:
                                      run.job.status === 'running'
                                        ? '停止并删除'
                                        : run.job.status === 'queued'
                                          ? '取消并删除'
                                          : '删除任务',
                                    danger: true,
                                  },
                                ],
                                onClick: ({ key }) => {
                                  if (key === 'repeat') {
                                    void repeatExtraction(run);
                                  } else if (key === 'adopt') {
                                    void adoptRun(run);
                                  } else if (key === 'delete') {
                                    void archiveExtraction(
                                      run.id,
                                      run.job.status,
                                    );
                                  }
                                },
                              }}
                            >
                              <Button
                                aria-label="操作"
                                loading={busyResultId === run.id}
                              >
                                操作
                              </Button>
                            </Dropdown>
                          </div>
                        </div>
                      </Card>
                    );
                  })}
                </div>
              ) : (
                <Empty description="这本书还没有提取结果" />
              )}
            </div>
          </Space>
        ) : null}
      </Drawer>

      <Modal
        title="上传 PDF 棋书"
        open={uploadOpen}
        onCancel={() => setUploadOpen(false)}
        onOk={() => void submitUpload()}
        okText="上传"
        confirmLoading={uploading}
        destroyOnHidden
      >
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
        </Form>
      </Modal>

      <Modal
        title="继续增量提取"
        open={appendDocument !== null}
        onCancel={() => setAppendDocumentId(undefined)}
        onOk={() => void submitAppend()}
        okText="登记任务"
        confirmLoading={busyResultId === appendDocument?.id}
        destroyOnHidden
      >
        {appendDocument && selectedAsset ? (
          <Form layout="vertical">
            <Typography.Paragraph type="secondary">
              当前已覆盖第 {appendDocument.first_page}–
              {appendDocument.last_page} 页。增量任务必须从下一页连续开始。
            </Typography.Paragraph>
            <Form.Item label="起始物理页">
              <InputNumber
                aria-label="增量起始物理页"
                className="w-full"
                disabled
                value={appendDocument.last_page + 1}
              />
            </Form.Item>
            <Form.Item label="结束物理页">
              <InputNumber
                aria-label="增量结束物理页"
                className="w-full"
                min={appendDocument.last_page + 1}
                max={selectedAsset.page_count}
                precision={0}
                value={appendLastPage}
                onChange={(value) => setAppendLastPage(value ?? undefined)}
              />
            </Form.Item>
            {appendError ? (
              <Typography.Paragraph type="danger">
                {appendError}
              </Typography.Paragraph>
            ) : null}
          </Form>
        ) : null}
      </Modal>

      <Modal
        title="添加其他资料"
        open={manualOpen}
        onCancel={() => setManualOpen(false)}
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
