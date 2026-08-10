import 'antd/dist/reset.css';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, theme } from 'antd';
import { BrowserRouter } from 'react-router-dom';
import { SWRConfig } from 'swr';

import { App } from './app/App';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#315c45',
          colorLink: '#0b57c0',
          colorLinkHover: '#073f91',
          colorTextSecondary: '#595959',
          borderRadius: 8,
        },
      }}
    >
      <SWRConfig value={{ revalidateOnFocus: false }}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </SWRConfig>
    </ConfigProvider>
  </React.StrictMode>,
);
