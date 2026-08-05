import { Alert, Card, Descriptions, Skeleton, Tag } from 'antd';
import useSWR from 'swr';

import { fetchJson } from '../logic/api/client';
import type { HealthResponse } from '../logic/api/types';

export function HealthStatus() {
  const { data, error, isLoading } = useSWR<HealthResponse>(
    '/api/health',
    fetchJson,
  );

  if (isLoading) {
    return (
      <Card title="系统状态" className="h-full shadow-sm">
        <Skeleton active paragraph={{ rows: 2 }} title={false} />
        <span className="sr-only">正在检查系统状态</span>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card title="系统状态" className="h-full shadow-sm">
        <Alert
          type="error"
          showIcon
          title="API 暂不可用"
          description="请确认 Sanic 服务已经启动，再重试。"
        />
      </Card>
    );
  }

  return (
    <Card
      title="系统状态"
      className="h-full shadow-sm"
      extra={<Tag color="success">服务正常</Tag>}
    >
      <Descriptions column={1} size="small">
        <Descriptions.Item label="API">{data.service}</Descriptions.Item>
        <Descriptions.Item label="版本">{data.version}</Descriptions.Item>
        <Descriptions.Item label="数据库">SQLite 已连接</Descriptions.Item>
      </Descriptions>
    </Card>
  );
}
