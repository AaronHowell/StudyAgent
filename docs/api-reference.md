# API Reference

当前 FastAPI 入口文件：

`apps/api/src/study_agent_api/main.py`

## Health

### `GET /healthz`

作用：
- 返回最小健康检查结果

返回：
- `status`
- `service`
- `environment`

## Document Scan

### `POST /documents/scan`

作用：
- 扫描一个本地目录下的 PDF
- 返回前端文档表格需要的基础字段

请求体：

```json
{
  "root_path": "C:\\Users\\Aaron_Howell\\Desktop\\postgraduate\\PaperStore"
}
```

返回重点：
- `id`
- `title`
- `file_name`
- `path`
- `status`
- `ingested`
- `modified_at`
- `content_hash`

## Visual Asset Preview

### `POST /documents/images`

作用：
- 对单篇 PDF 提取视觉资产摘要
- 返回图表画廊所需的字段

请求体：

```json
{
  "path": "C:\\Users\\Aaron_Howell\\Desktop\\postgraduate\\PaperStore\\STAC.pdf"
}
```

返回重点：
- `id`
- `document_id`
- `page_number`
- `file_name`
- `file_path`
- `file_url`
- `asset_kind`
- `asset_label`
- `caption`
- `summary`
- `asset_type`
- `keywords`

## Ingestion Status

### `POST /documents/ingestion-status`

作用：
- 查询某篇文档是否已入库

请求体：

```json
{
  "path": "C:\\Users\\Aaron_Howell\\Desktop\\postgraduate\\PaperStore\\STAC.pdf"
}
```

返回：
- `document_id`
- `path`
- `ingested`

## Single Ingestion

### `POST /documents/ingest`

作用：
- 提交单篇文档入库任务

请求体：

```json
{
  "project_id": "frontend-project",
  "path": "C:\\Users\\Aaron_Howell\\Desktop\\postgraduate\\PaperStore\\STAC.pdf"
}
```

返回：
- `task`

任务对象重点字段：
- `task_id`
- `state`
- `result`
- `error_message`
- `error_type`
- `error_code`
- `retryable`
- `timed_out`

## Batch Ingestion

### `POST /documents/ingest/batch`

作用：
- 批量提交多篇文档入库任务

请求体：

```json
{
  "project_id": "frontend-project",
  "paths": [
    "C:\\Users\\Aaron_Howell\\Desktop\\postgraduate\\PaperStore\\A.pdf",
    "C:\\Users\\Aaron_Howell\\Desktop\\postgraduate\\PaperStore\\B.pdf"
  ]
}
```

返回：
- `tasks`

## Ingestion Task Query

### `GET /documents/ingest/{task_id}`

作用：
- 查询单个入库任务的状态

### `GET /documents/ingest`

作用：
- 返回当前已知任务列表
- 前端任务面板用它做轮询刷新

## Local File Serve

### `GET /documents/file?path=...`

作用：
- 提供本地 PDF 或视觉资产文件给前端预览

说明：
- 当前用于 PDF iframe 预览和视觉资产 blob 读取

## 当前 API 状态

已验证可用：
- `/healthz`
- `/documents/scan`
- `/documents/ingest`
- `/documents/ingest/{task_id}`
- `/documents/ingest`
- `/documents/ingest/batch`
- `/documents/file`

说明：
- `documents/images` 对不同 PDF 的结果差异较大，依赖当前视觉资产提取能力
- 当前入库任务支持后台并发，但属于单进程轻量任务器
