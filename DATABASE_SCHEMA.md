# Database Schema

这份文档描述当前代码实现对应的 MySQL 与 Qdrant 结构。

适用代码：
- `packages/integrations/src/study_agent_integrations/mysql_repositories.py`
- `packages/integrations/src/study_agent_integrations/qdrant_store.py`

## MySQL

当前已经实现 4 张表：
- `projects`
- `documents`
- `document_assets`
- `chunks`

### `projects`

用途：
- 保存项目元数据

关键字段：
- `id`
- `name`
- `root_path`
- `description`

说明：
- `description` 当前是 `TEXT NOT NULL`
- 不使用 `DEFAULT ''`，以兼容当前 MySQL 环境

### `documents`

用途：
- 保存单篇文档元数据

关键字段：
- `id`
- `project_id`
- `path`
- `file_name`
- `doc_type`
- `title`
- `status`
- `content_hash`

说明：
- `content_hash` 用于跳过未变化文档
- `get_by_path(project_id, path)` 用于同路径重入库检测

### `document_assets`

用途：
- 保存视觉资产

关键字段：
- `id`
- `document_id`
- `page_number`
- `file_path`
- `file_name`
- `asset_kind`
- `asset_label`
- `asset_index`
- `caption`
- `summary`
- `asset_type`
- `keywords_json`
- `related_chunk_ids_json`
- `media_type`
- `metadata_json`

说明：
- 视觉资产统一使用 `DocumentAsset`
- 当前图、表、其它视觉区域都收敛到这一个实体

### `chunks`

用途：
- 保存正文分块

关键字段：
- `id`
- `project_id`
- `document_id`
- `chunk_index`
- `chunk_type`
- `text`
- `page`
- `section`
- `metadata_json`

说明：
- `chunk_index` 已经是正式字段
- 老表缺失时，仓储层会自动补列

## Qdrant

当前不是单 collection，而是三层 collection：

- `study_agent_documents`
- `study_agent_chunks`
- `study_agent_assets`

## `study_agent_documents`

用途：
- 文档级检索

named vectors：
- `title`
- `summary`

payload：
- `document_id`
- `project_id`
- `title`
- `file_name`
- `path`
- `keywords`

## `study_agent_chunks`

用途：
- 正文证据检索

named vectors：
- `content`
- `title`
- `summary`

payload：
- `chunk_id`
- `project_id`
- `document_id`
- `chunk_index`
- `chunk_type`
- `page`
- `section`

## `study_agent_assets`

用途：
- 视觉资产检索

named vectors：
- `caption`
- `summary`

payload：
- `asset_id`
- `document_id`
- `project_id`
- `page_number`
- `asset_kind`
- `asset_label`
- `asset_type`
- `file_name`

## 当前检索分层

建议使用顺序：

1. `documents`
   - 先找相关论文
2. `chunks`
   - 再找正文证据
3. `assets`
   - 再找图表证据

## 当前限制

- 视觉资产向量当前基于文本：
  - `caption`
  - `summary`
- 还未做真正的图片 embedding
