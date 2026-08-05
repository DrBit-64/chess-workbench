import { Card, Col, Row, Space, Tag, Typography } from 'antd';

import { HealthStatus } from '../components/HealthStatus';

const futureAreas = ['课程与局面图', '个人开局库', '间隔重复', '实战复盘'];

export function Dashboard() {
  return (
    <main className="mx-auto max-w-6xl px-6 py-12">
      <Space className="mb-8" orientation="vertical" size={4}>
        <Typography.Text className="tracking-[0.18em] text-emerald-800" strong>
          LOCAL-FIRST CHESS KNOWLEDGE SYSTEM
        </Typography.Text>
        <Typography.Title className="mb-0!" level={1}>
          把资料、局面与练习连成一条学习闭环
        </Typography.Title>
        <Typography.Paragraph className="max-w-3xl text-base text-stone-600">
          工程底座已就绪。下一阶段将从可识别转置的局面图和后端棋规验证开始。
        </Typography.Paragraph>
      </Space>

      <Row gutter={[24, 24]}>
        <Col xs={24} lg={10}>
          <HealthStatus />
        </Col>
        <Col xs={24} lg={14}>
          <Card title="接下来的领域切片" className="h-full shadow-sm">
            <Space wrap>
              {futureAreas.map((area) => (
                <Tag key={area} color="green">
                  {area}
                </Tag>
              ))}
            </Space>
          </Card>
        </Col>
      </Row>
    </main>
  );
}
