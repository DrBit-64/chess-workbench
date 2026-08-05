import { Button, Result } from 'antd';
import { Link } from 'react-router-dom';

export function NotFound() {
  return (
    <Result
      status="404"
      title="页面不存在"
      subTitle="当前功能还没有进入已实现的开发阶段。"
      extra={
        <Button type="primary">
          <Link to="/">返回首页</Link>
        </Button>
      }
    />
  );
}
