# Runtime data

此目录只保存本地运行数据，内容默认不进入版本控制。应用会按需创建以下子目录：

- `database/`：SQLite 数据库；
- `sources/`：原始 PDF、视频、PGN 等来源文件；
- `derived/`：OCR、页面渲染、关键帧等衍生文件；
- `engines/`：本地引擎；
- `tablebases/`：Syzygy 表库。

构建、测试和启动不能依赖这里已有任何文件；测试一律使用临时目录。
