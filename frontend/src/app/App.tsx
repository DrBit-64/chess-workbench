import { Layout, Menu, Spin, Typography } from 'antd';
import { lazy, Suspense } from 'react';
import { Link, Route, Routes, useLocation, useParams } from 'react-router-dom';

import { Dashboard } from './Dashboard';
import { NotFound } from './NotFound';

const CourseCatalog = lazy(() =>
  import('./CourseCatalog').then((module) => ({
    default: module.CourseCatalog,
  })),
);
const CourseEditor = lazy(() =>
  import('./CourseEditor').then((module) => ({ default: module.CourseEditor })),
);
const SourcesPage = lazy(() =>
  import('./SourcesPage').then((module) => ({ default: module.SourcesPage })),
);
const AnalysisPage = lazy(() =>
  import('./AnalysisPage').then((module) => ({ default: module.AnalysisPage })),
);
const PdfReviewPage = lazy(() =>
  import('./PdfReviewPage').then((module) => ({
    default: module.PdfReviewPage,
  })),
);

const navigation = [
  { key: '/', label: <Link to="/">首页</Link> },
  { key: '/learn', label: <Link to="/learn">学习</Link> },
  { key: '/sources', label: <Link to="/sources">资料</Link> },
  { key: '/analysis', label: <Link to="/analysis">引擎</Link> },
  { key: '/repertoire', label: '个人开局库', disabled: true },
  { key: '/practice', label: '练习', disabled: true },
  { key: '/games', label: '我的对局', disabled: true },
];

function PdfReviewPageAdapter() {
  const { runId } = useParams<{ runId: string }>();
  if (runId === undefined) {
    return <NotFound />;
  }
  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <header className="mb-4 flex flex-wrap items-baseline gap-4">
        <h1 className="text-2xl font-semibold text-stone-900">AI 棋书审核</h1>
        <Link
          to="/sources"
          className="text-sm text-stone-600 hover:text-stone-900"
        >
          ← 返回资料
        </Link>
      </header>
      <PdfReviewPage runId={runId} />
    </div>
  );
}

export function App() {
  const location = useLocation();
  const selected =
    navigation.find(
      (item) => item.key !== '/' && location.pathname.startsWith(item.key),
    )?.key ?? '/';
  return (
    <Layout className="min-h-screen bg-stone-50">
      <Layout.Header className="flex items-center gap-8 bg-stone-950 px-6">
        <Typography.Title
          className="m-0! whitespace-nowrap text-stone-50!"
          level={3}
        >
          ChessWorkbench
        </Typography.Title>
        <Menu
          className="min-w-0 flex-1"
          theme="dark"
          mode="horizontal"
          selectedKeys={[selected]}
          items={navigation}
        />
      </Layout.Header>
      <Layout.Content>
        <Suspense
          fallback={
            <div className="grid min-h-[70vh] place-items-center">
              <Spin size="large" />
            </div>
          }
        >
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/learn" element={<CourseCatalog />} />
            <Route path="/learn/:courseId" element={<CourseEditor />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route
              path="/sources/pdf-extractions/:runId/review"
              element={<PdfReviewPageAdapter />}
            />
            <Route path="/analysis" element={<AnalysisPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </Layout.Content>
    </Layout>
  );
}
