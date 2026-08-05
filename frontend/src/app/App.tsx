import { Layout, Menu, Typography } from 'antd';
import { Route, Routes } from 'react-router-dom';

import { Dashboard } from './Dashboard';
import { NotFound } from './NotFound';

const navigation = [
  { key: 'learn', label: '学习' },
  { key: 'repertoire', label: '个人开局库' },
  { key: 'practice', label: '练习' },
  { key: 'games', label: '我的对局' },
  { key: 'sources', label: '资料' },
];

export function App() {
  return (
    <Layout className="min-h-screen bg-stone-50">
      <Layout.Header className="flex items-center gap-8 bg-stone-950 px-6">
        <Typography.Title className="m-0! text-stone-50!" level={3}>
          ChessWorkbench
        </Typography.Title>
        <Menu
          className="min-w-0 flex-1"
          theme="dark"
          mode="horizontal"
          selectedKeys={[]}
          items={navigation}
        />
      </Layout.Header>
      <Layout.Content>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Layout.Content>
    </Layout>
  );
}
