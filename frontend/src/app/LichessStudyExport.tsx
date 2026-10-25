import {
  Alert,
  Button,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Typography,
} from 'antd';
import { useEffect, useState } from 'react';
import useSWR from 'swr';

import { fetchJson, requestJson } from '../logic/api/client';
import type { CourseModule } from '../logic/api/types';
import type { paths } from '../types/api.generated';

type StudyPreview =
  paths['/api/courses/{course_id}/lichess-study-preview']['get']['responses'][200]['content']['application/json'];
type StudyResult =
  paths['/api/courses/{course_id}/lichess-studies']['post']['responses'][200]['content']['application/json'];

const tokenPage = 'https://lichess.org/account/oauth/token';

export function LichessStudyExport({
  courseId,
  moduleId,
  courseTitle,
  modules,
  orientation,
  visible,
  onClose,
  unsavedChanges = false,
}: {
  courseId: string;
  moduleId?: string;
  courseTitle?: string;
  modules: CourseModule[];
  orientation: 'white' | 'black';
  visible?: boolean;
  onClose?: () => void;
  unsavedChanges?: boolean;
}) {
  const [localOpen, setLocalOpen] = useState(false);
  const open = visible ?? localOpen;
  const [scopeIds, setScopeIds] = useState<string[]>(
    moduleId ? [moduleId] : [],
  );
  const [name, setName] = useState('');
  const [customName, setCustomName] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [result, setResult] = useState<StudyResult>();
  const [publishError, setPublishError] = useState<string>();
  const chapters = modules.filter((item) => item.parent_id === null);
  const defaultScope = JSON.stringify(
    moduleId ? [moduleId] : chapters.map((item) => item.id),
  );
  const scopeQuery = new URLSearchParams();
  for (const id of scopeIds) scopeQuery.append('module_ids', id);
  const {
    data: preview,
    error,
    isLoading,
  } = useSWR<StudyPreview>(
    open && scopeIds.length
      ? `/api/courses/${courseId}/lichess-study-preview?${scopeQuery}`
      : null,
    fetchJson,
    { revalidateOnFocus: false },
  );

  useEffect(() => {
    if (preview && !customName) setName(preview.name);
  }, [preview, customName]);

  useEffect(() => {
    if (visible) {
      setScopeIds(JSON.parse(defaultScope) as string[]);
      setCustomName(false);
      setResult(undefined);
      setPublishError(undefined);
    }
  }, [visible, defaultScope]);

  function close() {
    setLocalOpen(false);
    onClose?.();
  }

  async function publish() {
    if (publishing || result || !preview || !scopeIds.length || !name.trim())
      return;
    setPublishing(true);
    setPublishError(undefined);
    try {
      setResult(
        await requestJson<StudyResult>(
          `/api/courses/${courseId}/lichess-studies`,
          {
            method: 'POST',
            body: JSON.stringify({
              module_ids: scopeIds,
              name: name.trim(),
              orientation,
            }),
          },
        ),
      );
    } catch (caught) {
      setPublishError(
        caught instanceof Error
          ? caught.message
          : '未能取得发布结果，请先检查 Lichess 我的研讨，避免重复创建',
      );
    } finally {
      setPublishing(false);
    }
  }

  return (
    <>
      {visible === undefined ? (
        <Button
          onClick={() => {
            setScopeIds(JSON.parse(defaultScope) as string[]);
            setCustomName(false);
            setResult(undefined);
            setPublishError(undefined);
            setLocalOpen(true);
          }}
        >
          所选章节发送到 Lichess
        </Button>
      ) : null}
      <Modal
        title="创建 Lichess 研讨"
        open={open}
        width={620}
        onCancel={close}
        closable={!publishing}
        mask={{ closable: !publishing }}
        keyboard={!publishing}
        footer={[
          <Button key="close" disabled={publishing} onClick={close}>
            关闭
          </Button>,
          <Button
            key="publish"
            type="primary"
            loading={publishing}
            disabled={
              !!result ||
              !!publishError ||
              isLoading ||
              !!error ||
              !scopeIds.length ||
              !preview?.token_configured ||
              !preview.chapters.length ||
              !!preview.blockers.length ||
              !name.trim() ||
              unsavedChanges
            }
            onClick={() => void publish()}
          >
            {result ? '已结束本次发送' : '创建并发送'}
          </Button>,
        ]}
      >
        <Space orientation="vertical" size="middle" className="w-full">
          <Typography.Paragraph className="mb-0!">
            将已保存的棋谱和注释发送到你的 Lichess 账户，创建新的研讨。
            默认不公开列出，持链接的人可以查看；可见性可在 Lichess 中修改。
            每次发送都会新建研讨，之后两边的修改不会自动同步。
          </Typography.Paragraph>
          <div>
            {courseTitle ? (
              <Typography.Paragraph type="secondary" className="mb-2!">
                课程：{courseTitle}
              </Typography.Paragraph>
            ) : null}
            <label htmlFor="lichess-export-scope">发送范围</label>
            <Select
              id="lichess-export-scope"
              aria-label="发送范围"
              mode="multiple"
              maxTagCount="responsive"
              optionFilterProp="label"
              placeholder="选择要发送的章节或小节"
              className="w-full"
              value={scopeIds}
              disabled={publishing || !!result || !!publishError}
              options={[
                {
                  label: '一级章节（含所有小节）',
                  options: chapters.map((item) => ({
                    value: item.id,
                    label: `整个章节：${item.title}（含所有小节）`,
                  })),
                },
                {
                  label: '单独小节',
                  options: modules
                    .filter((item) => item.parent_id !== null)
                    .map((item) => ({
                      value: item.id,
                      label: `${modules.find((parent) => parent.id === item.parent_id)?.title ?? ''} / ${item.title}`,
                    })),
                },
              ]}
              onChange={(value: string[]) => setScopeIds(value)}
            />
            <Space className="mt-1">
              <Button
                type="link"
                size="small"
                disabled={publishing || !!result || !!publishError}
                onClick={() => setScopeIds(chapters.map((item) => item.id))}
              >
                全选一级章节
              </Button>
              <Button
                type="link"
                size="small"
                disabled={publishing || !!result || !!publishError}
                onClick={() => setScopeIds([])}
              >
                清空选择
              </Button>
            </Space>
            <Typography.Paragraph type="secondary" className="mb-0!">
              可多选。选择一级章节会包含全部小节；重叠选择的小节只发送一次，按课程目录顺序排列。
            </Typography.Paragraph>
          </div>
          {!scopeIds.length ? (
            <Alert type="info" title="请至少选择一个章节或小节" />
          ) : null}
          {unsavedChanges ? (
            <Alert
              type="warning"
              title="请先保存当前说明的修改，再发送到 Lichess"
            />
          ) : null}
          {isLoading ? <Spin aria-label="准备研讨章节" /> : null}
          {error ? (
            <Alert
              type="error"
              title="无法准备所选棋谱，请关闭后重试或检查该章节是否能导出 PGN"
            />
          ) : null}
          {preview ? (
            <>
              {!preview.token_configured ? (
                <Alert
                  type="info"
                  title="首次使用需要配置 Lichess 令牌"
                  description={
                    <div>
                      在{' '}
                      <a href={tokenPage} target="_blank" rel="noreferrer">
                        Lichess 令牌页面
                      </a>{' '}
                      创建仅带
                      <code> study:write </code>{' '}
                      权限的个人令牌，保存到仓库外的单行文件（权限 600）。
                      在本地 .env 设置{' '}
                      <code>CHESS_WORKBENCH_LICHESS_API_TOKEN_FILE</code>{' '}
                      为文件绝对路径， 重启后端后重新打开此窗口。详细步骤见
                      README。
                    </div>
                  }
                />
              ) : null}
              <div>
                <label htmlFor="lichess-study-name">研讨名称</label>
                <Input
                  id="lichess-study-name"
                  value={name}
                  maxLength={100}
                  disabled={publishing || !!result}
                  onChange={(event) => {
                    setCustomName(true);
                    setName(event.target.value);
                  }}
                />
              </div>
              <div>
                <Typography.Text strong>
                  将创建 {preview.chapters.length} 个研讨章节
                </Typography.Text>
                <ol className="my-2 max-h-60 overflow-auto pl-6">
                  {preview.chapters.map((chapter) => (
                    <li key={chapter.module_id}>
                      {chapter.name} ·{' '}
                      {chapter.move_count
                        ? `${chapter.move_count} 个半回合`
                        : '空章节（无棋步）'}
                    </li>
                  ))}
                </ol>
                <Typography.Text type="secondary">
                  按课程目录顺序导出：一级章节先作为目录页，二级小节随后排列，并保留各自的原始标题。
                  如果大章节本身已有棋谱，它会留在首章。主线、支线、起始局面、棋步标注和文字注释会随棋谱发送；
                  PDF、图片文件和原书定位不随棋谱发送，注释不保留 Markdown
                  版式。
                </Typography.Text>
              </div>
              {preview.skipped_modules.length ? (
                <Typography.Paragraph type="secondary" className="mb-0!">
                  没有棋谱，未发送：{preview.skipped_modules.join('、')}
                  （这些条目的独立正文也不会发送）
                </Typography.Paragraph>
              ) : null}
              {preview.warnings.map((warning) => (
                <Alert key={warning} type="warning" title={warning} />
              ))}
              {preview.blockers.map((blocker) => (
                <Alert key={blocker} type="error" title={blocker} />
              ))}
            </>
          ) : null}
          {publishError ? (
            <Alert
              type="error"
              title={publishError}
              description={
                <a
                  href="https://lichess.org/study/mine/hot"
                  target="_blank"
                  rel="noreferrer"
                >
                  查看 Lichess 我的研讨，再决定是否重新发送
                </a>
              }
            />
          ) : null}
          {result ? (
            <Alert
              type={result.status === 'complete' ? 'success' : 'warning'}
              title={result.message}
              description={
                <a href={result.study_url} target="_blank" rel="noreferrer">
                  打开 Lichess 研讨
                </a>
              }
            />
          ) : null}
        </Space>
      </Modal>
    </>
  );
}
