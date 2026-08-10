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
import { Link } from 'react-router-dom';
import useSWR from 'swr';

import { fetchJson, requestJson } from '../logic/api/client';
import type { Course } from '../logic/api/types';

export function CourseCatalog() {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<string>();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const key = useMemo(() => {
    const params = new URLSearchParams({ sort: 'updated_desc' });
    if (query.trim()) params.set('q', query.trim());
    if (mode) params.set('mode', mode);
    return `/api/courses?${params.toString()}`;
  }, [mode, query]);
  const { data = [], isLoading, mutate } = useSWR<Course[]>(key, fetchJson);

  async function createCourse(values: { title: string; mode: string }) {
    await requestJson<Course>('/api/courses', {
      method: 'POST',
      body: JSON.stringify(values),
    });
    setOpen(false);
    form.resetFields();
    await mutate();
    void message.success('课程已创建');
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <Typography.Title className="mb-1!" level={2}>
            Learn
          </Typography.Title>
          <Typography.Text type="secondary">
            课程、章节与局面知识
          </Typography.Text>
        </div>
        <Button type="primary" onClick={() => setOpen(true)}>
          新建课程
        </Button>
      </div>
      <Space className="mb-6 w-full" wrap>
        <Input.Search
          aria-label="搜索课程"
          allowClear
          placeholder="搜索标题、说明或分类"
          className="w-80"
          onSearch={setQuery}
        />
        <Select
          aria-label="课程模式"
          allowClear
          placeholder="全部模式"
          className="w-44"
          value={mode}
          onChange={setMode}
          options={[
            { value: 'traditional', label: '传统课程' },
            { value: 'opening_explorer', label: '开局探索器' },
          ]}
        />
      </Space>
      {data.length === 0 && !isLoading ? (
        <Empty description="没有匹配的课程" />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((course) => (
            <Link
              key={course.id}
              to={`/learn/${course.id}`}
              className="block text-inherit"
            >
              <Card
                loading={isLoading}
                hoverable
                title={course.title}
                extra={
                  <Tag
                    color={course.status === 'published' ? 'green' : 'default'}
                  >
                    {course.status === 'published' ? '已发布' : '草稿'}
                  </Tag>
                }
              >
                <Typography.Paragraph className="min-h-12 text-stone-600">
                  {course.description || '尚未添加课程说明'}
                </Typography.Paragraph>
                <Space wrap>
                  <Tag
                    color={course.mode === 'traditional' ? 'blue' : 'purple'}
                  >
                    {course.mode === 'traditional' ? '传统课程' : '开局探索器'}
                  </Tag>
                  {course.tags.map((tag) => (
                    <Tag key={tag}>{tag}</Tag>
                  ))}
                </Space>
              </Card>
            </Link>
          ))}
        </div>
      )}
      <Modal
        title="新建课程"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        okText="创建"
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ mode: 'traditional' }}
          onFinish={(values) =>
            void createCourse(values as { title: string; mode: string })
          }
        >
          <Form.Item
            name="title"
            label="课程名称"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input autoFocus maxLength={200} />
          </Form.Item>
          <Form.Item name="mode" label="组织方式" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'traditional', label: '传统课程（按来源组织）' },
                {
                  value: 'opening_explorer',
                  label: '开局探索器（按决策点组织）',
                },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}
