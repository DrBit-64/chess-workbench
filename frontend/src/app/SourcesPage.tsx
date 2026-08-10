import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import { useMemo, useState } from 'react';
import useSWR from 'swr';

import { fetchJson, requestJson } from '../logic/api/client';
import type { CitableSource, Source } from '../logic/api/types';

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

export function SourcesPage() {
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState<string>();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const key = useMemo(() => {
    const params = new URLSearchParams();
    if (query.trim()) params.set('q', query.trim());
    if (kind) params.set('kind', kind);
    return `/api/sources${params.size ? `?${params.toString()}` : ''}`;
  }, [kind, query]);
  const { data = [], mutate } = useSWR<Source[]>(key, fetchJson);

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
      {data.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((source) => (
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
