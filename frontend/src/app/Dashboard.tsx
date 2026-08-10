import {
  Alert,
  Button,
  Card,
  Col,
  Row,
  Skeleton,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd';
import { Link } from 'react-router-dom';
import useSWR from 'swr';

import { HealthStatus } from '../components/HealthStatus';
import { fetchJson } from '../logic/api/client';
import type { DashboardSummary } from '../logic/api/types';

export function Dashboard() {
  const { data, error, isLoading } = useSWR<DashboardSummary>(
    '/api/dashboard/summary',
    fetchJson,
  );
  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-6">
        <Space orientation="vertical" size={4}>
          <Typography.Text
            className="tracking-[0.18em] text-emerald-800"
            strong
          >
            LOCAL-FIRST CHESS KNOWLEDGE SYSTEM
          </Typography.Text>
          <Typography.Title className="mb-0!" level={1}>
            你的棋局知识工作台
          </Typography.Title>
          <Typography.Paragraph className="mb-0! max-w-3xl text-base text-stone-600">
            从来源建立课程，在可识别转置的局面图上整理分支与解释。
          </Typography.Paragraph>
        </Space>
        <Space>
          <Link to="/sources">
            <Button>添加资料</Button>
          </Link>
          <Link to="/learn">
            <Button type="primary">打开课程</Button>
          </Link>
        </Space>
      </div>

      {error ? (
        <Alert type="error" showIcon title="无法读取工作台统计" />
      ) : null}
      <Skeleton loading={isLoading} active paragraph={{ rows: 3 }}>
        {data ? (
          <Row gutter={[16, 16]} className="mb-6">
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="课程" value={data.course_count} />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="章节" value={data.module_count} />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="资料" value={data.source_count} />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="知识笔记" value={data.knowledge_note_count} />
              </Card>
            </Col>
          </Row>
        ) : null}
      </Skeleton>

      <Row gutter={[24, 24]}>
        <Col xs={24} lg={9}>
          <HealthStatus />
        </Col>
        <Col xs={24} lg={15}>
          <Card title="最近课程" className="h-full shadow-sm">
            {data?.recent_courses.length ? (
              <Space orientation="vertical" className="w-full" size="middle">
                {data.recent_courses.map((course) => (
                  <Link
                    key={course.id}
                    to={`/learn/${course.id}`}
                    className="flex justify-between rounded-lg border border-stone-200 p-3 text-stone-900"
                  >
                    <span>{course.title}</span>
                    <Tag
                      color={course.mode === 'traditional' ? 'blue' : 'purple'}
                    >
                      {course.mode === 'traditional'
                        ? '传统课程'
                        : '开局探索器'}
                    </Tag>
                  </Link>
                ))}
              </Space>
            ) : (
              <div className="py-8 text-center text-stone-500">
                还没有课程，从 Learn 创建第一门课程。
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </main>
  );
}
