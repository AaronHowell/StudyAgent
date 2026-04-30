# PaperLab 后端学习路线

这份文档只讲后端。目标不是一次看完所有代码，而是按合理路线建立整体地图：先知道请求从哪里进来，再理解领域模型、入库、检索、回答、复现 run，最后再看 LangGraph orchestration。

建议学习时始终配合测试：

```bash
cd PaperLab/Server
uv run pytest -q
```

## 1. 后端整体功能地图

当前 PaperLab 后端主要有五类能力：

1. API 服务：FastAPI 路由、请求 schema、依赖装配。
2. 论文入库：扫描 PDF、解析正文和图片、切 chunk、写数据库、写向量索引。
3. 论文检索与回答：检索文档、正文 chunk、图片/图表 asset，生成带引用的回答。
4. Agent orchestration：基于 LangGraph 的多 worker 协调问答。
5. 论文复现 run：后台创建复现任务 DAG，生成最小复现代码、执行命令、保存日志和报告。

先建立一条主线：

```text
HTTP 请求
  -> api/routes/*
  -> usecases/*
  -> domain ports
  -> integrations/*
  -> 返回 API response 或 SSE event
```

后端代码目录大致分工：

```text
PaperLab/Server/
  api/                 FastAPI 层
  src/domain/          核心数据模型和协议接口
  src/documents/       PDF 扫描、解析、chunking
  src/indexing/        文档/chunk/asset 向量索引
  src/retrieval/       检索融合和 EvidencePack 构造
  src/generation/      Prompt/message/citation 构造
  src/usecases/        应用层用例，串联业务流程
  src/integrations/    MySQL、Qdrant、Redis、LLM、MCP、sandbox
  src/orchestration/   LangGraph supervisor
  src/workers/         worker agent 和 reproduction workers
  tests/               后端测试
```

## 2. API 层

先读 API 层，因为它告诉你外部怎么进入系统。

### `api/main.py`

主要职责：

- 创建 FastAPI app。
- 注册 CORS。
- 注册 lifespan。
- include 各个 router。
- 保留 `/desktop/project-folder/select` 文件夹选择接口。
- 提供 `uvicorn` 启动入口。

关键函数/对象：

- `app`
  - FastAPI 应用实例。
  - 所有 route 都通过 `app.include_router(...)` 接入。

- `lifespan(...)`
  - API 生命周期钩子。
  - 服务关闭时会关闭 ingestion task manager。

- `_select_directory_path(current_path)`
  - 调用 tkinter 打开本地文件夹选择器。
  - 这是偏 desktop 的接口，不属于核心业务。

- `select_project_folder(payload)`
  - `/desktop/project-folder/select`
  - 包装 `_select_directory_path`，返回选中的绝对路径。

阅读重点：

- `main.py` 不应该有业务逻辑。
- 看到 endpoint 行为时，不要在这里找，去 `api/routes/*`。

验证：

```bash
uv run pytest tests/test_entrypoints.py::EntrypointTest::test_health_endpoint -q
```

### `api/dependencies.py`

主要职责：

- 从环境变量加载 settings。
- 创建 MySQL repository。
- 创建 Redis cache。
- 创建 Qdrant vector store。
- 创建 embedding provider、reranker、LLM provider。
- 创建 usecase。
- 通过 `get_services()` 给 route 层复用依赖。

关键类/函数：

- `ApiServices`
  - 一个 dataclass，集中保存 route 层需要的服务。
  - 里面包括 `document_scanner`、`pdf_parser`、repositories、`retrieve_evidence_use_case`、`answer_question_use_case`、`ingestion_task_manager`。

- `settings`
  - `Settings.from_env()` 的结果。
  - API 全局配置。

- `get_services()`
  - `@lru_cache(maxsize=1)`，所以同一个进程里只初始化一次。
  - route 层通过它拿服务。
  - 这里是理解“后端依赖怎么连起来”的核心文件。

阅读重点：

- 看 `get_services()` 的初始化顺序。
- 看哪些配置为空时会导致功能不可用。
- 例如没有 embedding 或 Qdrant 时，`retrieve_evidence_use_case` 会是 `None`。

常见修改：

- 新增一个全局 usecase 时，通常在这里装配。
- 新增一个外部服务适配器时，也通常在这里接入。

### `api/schemas.py`

主要职责：

- 定义 FastAPI request/response 的 Pydantic model。
- API 层对外的数据结构都应该在这里可见。

关键模型：

- `ScanDocumentsRequest` / `ScanDocumentsResponse`
  - 扫描本地论文目录。

- `DocumentImagesRequest` / `DocumentImagesResponse`
  - 读取一篇 PDF 的图片资产信息。

- `IngestDocumentRequest` / `IngestDocumentResponse`
  - 单篇论文入库。

- `RetrieveEvidenceRequest` / `RetrievalEvidenceResponse`
  - 证据检索 API。

- `AgentAnswerStreamRequest`
  - `/agent/answer/stream` 使用的请求模型。

- `CreateReproductionRunRequest` / `ReproductionRunResponse`
  - 论文复现 run API。

阅读重点：

- 后端给前端新增字段时，优先新增字段，不要删除旧字段。
- `ChatTurnResponse` 里有 `asset_citations`、`asset_sources`，用于恢复聊天历史时保留图片证据。

## 3. API Routes

### `api/routes/health.py`

主要职责：

- 健康检查。

关键函数：

- `healthz()`
  - `GET /healthz`
  - 返回服务名、环境、状态。

### `api/routes/documents.py`

主要职责：

- 本地论文扫描。
- PDF 图片预览。
- 文档文件读取。
- 文档是否已入库查询。

关键函数：

- `is_document_ingested(document_id)`
  - 查询 MySQL 中是否已有该文档。
  - 扫描目录时用它标记 `ingested` 状态。

- `scan_documents(payload)`
  - `POST /documents/scan`
  - 输入本地目录。
  - 调用 `LocalDocumentScanner.scan_project_documents` 找 PDF。
  - 为每个 PDF 构造 `DocumentListItem`。

- `get_document_images(payload)`
  - `POST /documents/images`
  - 如果文档已入库，从 asset repository 读取图片资产。
  - 如果未入库，临时解析 PDF 获取图片预览。

- `get_document_ingestion_status(payload)`
  - `POST /documents/ingestion-status`
  - 根据本地路径构造 document id，再判断是否入库。

- `get_document_file(path)`
  - `GET /documents/file`
  - 返回本地文件，用于 PDF 或图片预览。

阅读重点：

- route 不做复杂业务，只调用 scanner/parser/repository。
- 当前 project id 有一些地方写成 `frontend-project`，这是后续可改进点。

### `api/routes/ingestion.py`

主要职责：

- 提交入库任务。
- 查询入库任务状态。
- 批量提交入库任务。

关键函数：

- `to_ingestion_task_summary(task_id)`
  - 把内部 ingestion task 转成 API response。
  - 所有 ingestion task response 都走它，避免重复字段映射。

- `ingest_document(payload)`
  - `POST /documents/ingest`
  - 检查文件存在后提交后台入库任务。

- `get_ingestion_task(task_id)`
  - `GET /documents/ingest/{task_id}`
  - 查询单个任务状态。

- `list_ingestion_tasks()`
  - `GET /documents/ingest`
  - 查询最近入库任务。

- `batch_ingest_documents(payload)`
  - `POST /documents/ingest/batch`
  - 批量提交文件路径。

阅读重点：

- 入库是后台任务，不阻塞 HTTP 请求。
- 真正入库逻辑在 `IngestDocumentUseCase`，不在 route。

### `api/routes/retrieval.py`

主要职责：

- 提供证据检索接口。

关键函数：

- `retrieve_evidence(payload)`
  - `POST /retrieval/evidence`
  - 调用 `RetrieveEvidenceUseCase.retrieve(...)`。
  - 返回 documents、text_chunks、assets、citations。

阅读重点：

- 如果 embedding 或 vector store 没配置，会返回 503。
- route 只把 `EvidencePack` 映射成 API response。

### `api/routes/assets.py`

主要职责：

- 返回某个图片/图表 asset 的二进制内容。

关键函数：

- `get_asset_content(asset_id)`
  - `GET /documents/assets/{asset_id}/content`
  - 优先从 Redis cache 读取。
  - cache miss 时从 asset repository 读取 MySQL。
  - 成功后会回写 Redis cache。

阅读重点：

- 这是图片证据卡片实际加载图片的接口。
- 不要把图片 bytes 放进 `EvidencePack`，这里只在需要展示时读取。

### `api/routes/chat.py`

主要职责：

- 提供简单 grounded answer 的 SSE 流式接口。

关键函数：

- `stream_agent_answer(payload)`
  - `POST /agent/answer/stream`
  - 调用 `AnswerQuestionUseCase.stream_answer(...)`。
  - 把 usecase 事件转成 SSE frame。

阅读重点：

- 这里不是 LangGraph 主聊天接口。
- LangGraph chat/session route 仍在 `api/chat.py`。

### `api/routes/runs.py`

主要职责：

- 创建、查询、暂停、恢复、取消论文复现 run。

关键函数：

- `_build_plan_agent()`
  - 创建 `FileReproductionStore`、`FileMailbox`、lock、workers、`PlanAgent`。

- `_lock()`
  - 如果 Redis cache store 可用，返回 `RedisReproductionLock`。
  - 否则返回 `NullReproductionLock`。

- `create_reproduction_run(payload)`
  - `POST /runs/reproduce`
  - 创建 run 后启动后台 `PlanAgent.run(run_id)`。

- `get_reproduction_run(run_id)`
  - `GET /runs/{run_id}`
  - 返回 run 状态、tasks、artifacts、report_path。

- `get_reproduction_run_events(run_id)`
  - `GET /runs/{run_id}/events`
  - 返回 run events。

- `pause_reproduction_run(run_id)`
  - 设置 run 为 `paused`。

- `resume_reproduction_run(run_id)`
  - 重新启动后台 PlanAgent。

- `cancel_reproduction_run(run_id)`
  - 设置 run 为 `cancelled`，并取消当前后台 task。

阅读重点：

- run 状态是文件持久化，不依赖前端内存。
- Redis 只做锁，不做事实存储。

## 4. Domain 层

Domain 是系统的核心数据语言。先读这里，后面读 usecase 会轻松很多。

### `src/domain/models.py`

主要职责：

- 定义核心 dataclass 和 enum。
- 这里是全局领域模型的集中定义。

关键 enum：

- `DocumentType`
  - `PDF`、`MARKDOWN`

- `DocumentStatus`
  - `DISCOVERED`、`INDEXED`、`FAILED`

- `ChunkType`
  - `TEXT`、`IMAGE`、`WEB`

- `MemoryType`
  - 长期记忆类型。

关键 dataclass：

- `Project`
  - 一个研究项目的元信息。

- `Document`
  - 一篇论文或文档。
  - 关键字段：`id`、`project_id`、`path`、`title`、`status`、`content_hash`。

- `PdfPage`
  - PDF 某一页的纯文本。

- `DocumentAsset`
  - 从论文中提取的图片/图表资产。
  - 关键字段：`id`、`document_id`、`page_number`、`file_path`、`caption`、`summary`、`content_bytes`。
  - `figure_label`、`figure_index` 是兼容旧调用的 property。

- `DocumentProfile`
  - 文档级检索画像。
  - 用于先检索“哪篇论文相关”。

- `Chunk`
  - 正文分块。
  - 关键字段：`id`、`document_id`、`chunk_index`、`text`、`page`、`section`。

- `Citation`
  - 正文证据引用。

- `AssetCitation`
  - 图片/图表证据引用。

- `ScoredId`
  - 向量检索返回的业务 id 和分数。

- `DocumentHit`、`ChunkHit`、`AssetHit`
  - 检索命中包装类。
  - 用 property 暴露常用字段，减少上层访问嵌套对象。

- `EvidencePack`
  - 检索结果总包。
  - 包含 documents、text_chunks、assets、citations、asset_citations。

阅读重点：

- 这些对象不应该依赖 FastAPI、MySQL、Qdrant、Redis。
- 如果一个字段是 API 特有的，通常不应该放进 domain。

### `src/domain/documents.py`

主要职责：

- 文档相关模型的 re-export。
- 让读者能从文件名快速找到文档模型。

包含：

- `Document`
- `DocumentAsset`
- `DocumentProfile`
- `PdfPage`
- `Project`
- `ScanSummary`

### `src/domain/evidence.py`

主要职责：

- 证据和检索相关模型的 re-export。

包含：

- `Chunk`
- `Citation`
- `AssetCitation`
- `DocumentHit`
- `ChunkHit`
- `AssetHit`
- `EvidencePack`
- `ScoredId`

### `src/domain/ports.py`

主要职责：

- 定义系统依赖的协议接口。
- usecase 面向这些 Protocol 编程，而不是直接写死某个实现。

关键 Protocol：

- `LLMProvider`
  - `generate(prompt)`
  - `stream_generate(prompt)`

- `EmbeddingProvider`
  - `embed_texts(texts)`
  - `embed_images(image_paths)`

- `RerankerProvider`
  - `rerank(query, candidates, top_k)`

- `VectorStore`
  - `search_documents`
  - `search_chunks`
  - `search_assets`
  - `upsert_chunks`
  - `delete_by_document`

- `DocumentRepository`
  - 文档元数据存储接口。

- `DocumentAssetRepository`
  - 图片资产存储接口。

- `ChunkRepository`
  - chunk 存储接口。

阅读重点：

- 如果你要替换 Qdrant 或 MySQL，优先看这些 port。
- 如果 usecase 里直接依赖具体实现，说明边界可能变差了。

## 5. 论文扫描、解析和切块

### `src/documents/document_scan.py`

主要职责：

- 扫描本地项目目录，找到支持的文档。
- 构造 `Document` 记录。

常见关键类/函数：

- `LocalDocumentScanner`
  - 扫描本地目录。
  - 根据文件路径、hash、项目 id 构造文档对象。

阅读重点：

- document id 如何生成。
- content hash 如何参与“是否需要重新入库”的判断。

### `src/documents/pdf_parser.py`

主要职责：

- 解析 PDF 元数据。
- 提取每页文本。
- 提取图片/图表 asset。

关键功能：

- 解析 PDF pages，生成 `PdfPage`。
- 解析图片，生成 `DocumentAsset`。
- 可选择是否导出图片文件。

阅读重点：

- 图片 asset 的 `caption`、`summary`、`file_path`、`content_bytes` 是怎么来的。
- 阶段二图片证据展示依赖这些字段。

### `src/documents/chunking.py`

主要职责：

- 把 `PdfPage` 文本切成可检索 chunk。

关键类/函数：

- `TextChunkBuilder`
  - 输入 `Document` 和 `PdfPage` 列表。
  - 输出 `Chunk` 列表。

阅读重点：

- chunk 的 `chunk_index`、`page`、`section` 如何设置。
- 检索引用 `[C1]` 最终依赖 chunk 的 page 和 text。

## 6. 入库 UseCase 和 Indexing

### `src/usecases/ingest_document.py`

主要职责：

- 编排单篇论文入库流程。

关键类：

- `IngestDocumentResult`
  - 入库结果摘要。
  - 包含 document、assets、chunks、status、message。

- `IngestOutcome`
  - `INDEXED`、`SKIPPED`、`UPDATED`、`FAILED`

- `IngestDocumentUseCase`
  - 入库主流程。

关键方法：

- `ingest(document, export_assets=False)`
  - 核心入库流程。
  - 判断是否已入库且 hash 未变。
  - 调用 PDF parser。
  - 调用 chunk builder。
  - 写 document、assets、chunks 到 repository。
  - 调用 `_index_vectors(...)` 写向量索引。

- `ingest_from_path(project_id, path)`
  - 更贴近 API 的入口。
  - 从本地 path 构造 `Document` 后调用 `ingest(...)`。

- `_delete_existing_document(document_id)`
  - 文档内容变化时，删除旧 chunk、asset、document 和向量索引。

- `_index_vectors(document, chunks, assets)`
  - 调用 `DocumentIndexer`、`ChunkIndexer`、`AssetIndexer`。

阅读重点：

- 这个文件现在负责“流程”，不负责具体索引细节。
- 不要把向量构造逻辑重新写回这里。

### `src/indexing/document_indexer.py`

主要职责：

- 构造文档级检索画像。
- 写文档级向量索引。

关键类/方法：

- `DocumentIndexer`

- `build_profile(document, chunks, assets)`
  - 用标题、前几个 chunk、asset label 构造 `DocumentProfile`。
  - 提取少量关键词。

- `index_profile(profile)`
  - embed title 和 summary。
  - ensure document collection。
  - upsert document profile vectors。

阅读重点：

- 文档级检索是“先找相关论文”的第一层。

### `src/indexing/chunk_indexer.py`

主要职责：

- 写正文 chunk 向量索引。

关键类/方法：

- `ChunkIndexer`

- `index_chunks(document, chunks)`
  - 为每个 chunk 构造 content/title/summary 三类文本。
  - 调用 embedding。
  - 调用 vector store 的 `upsert_chunk_vectors(...)`。

- `_summarize_chunk(text)`
  - 轻量截断 summary。

阅读重点：

- chunk 检索主要靠 content vector。
- title/summary vector 是扩展检索策略的预留。

### `src/indexing/asset_indexer.py`

主要职责：

- 写图片/图表 asset 向量索引。

关键类/方法：

- `AssetIndexer`

- `index_assets(assets)`
  - 构造 caption texts。
  - 构造 summary texts。
  - 可选构造 image vectors。
  - 调用 vector store 的 `upsert_assets(...)`。

- `_try_embed_images(assets)`
  - 只有所有 asset 都有可读 `file_path` 且 embedding provider 支持 `embed_images` 时才返回 image vectors。
  - 失败时返回 `None`，不影响 caption/summary 索引。

阅读重点：

- 当前默认图片召回靠 caption/summary。
- image vector 是 optional，不是系统运行的硬依赖。

相关测试：

```bash
uv run pytest tests/test_indexing_and_assets.py -q
```

## 7. 向量存储和外部集成

### `src/integrations/vectorstore/qdrant_store.py`

主要职责：

- Qdrant 向量库适配器。
- 管理 document、chunk、asset 三类 collection。

关键常量：

- `CHUNK_VECTOR_CONTENT`
- `DOCUMENT_VECTOR_TITLE`
- `DOCUMENT_VECTOR_SUMMARY`
- `ASSET_VECTOR_CAPTION`
- `ASSET_VECTOR_SUMMARY`
- `ASSET_VECTOR_IMAGE`

关键类：

- `QdrantConnectionConfig`
  - Qdrant 连接配置。

- `QdrantChunkVectorStore`
  - 实际 vector store 实现。

关键方法：

- `ensure_chunk_collection(...)`
  - 确保 chunk collection 存在。

- `ensure_document_collection(...)`
  - 确保 document profile collection 存在。

- `ensure_asset_collection(caption_vector_size, summary_vector_size, image_vector_size=None)`
  - 确保 asset collection 存在。
  - 如果传了 image_vector_size，会创建 image named vector。

- `upsert_chunk_vectors(...)`
  - 写 chunk vectors。

- `upsert_document_profiles(...)`
  - 写 document profile vectors。

- `upsert_assets(..., image_vectors=None)`
  - 写 caption/summary vectors。
  - 如果提供 image_vectors，也写 image vector。

- `search_documents(...)`
  - 文档级检索。

- `search_chunks(...)`
  - chunk 检索。

- `search_assets(...)`
  - asset 检索。

阅读重点：

- 业务层只关心 `ScoredId`，不直接处理 Qdrant point。
- Qdrant payload 里保存业务 id，例如 `chunk_id`、`asset_id`。

### `src/integrations/storage/mysql_repositories.py`

主要职责：

- MySQL repository 实现。
- 存 document、asset、chunk 等数据。

建议读法：

- 找 `MySQLDocumentRepository`
- 找 `MySQLDocumentAssetRepository`
- 找 `MySQLChunkRepository`

重点理解：

- `replace_for_document(...)` 如何替换某篇文档的 assets/chunks。
- `list_by_ids(...)` 如何把向量检索得到的 id 转回领域对象。
- `load_content(asset_id)` 如何取图片 bytes。

### `src/integrations/storage/redis_cache.py`

主要职责：

- Redis JSON cache。
- Redis lock。
- 图片内容短期 cache。

关键类/方法：

- `RedisCacheStore`

- `get_json` / `set_json`
  - JSON 缓存。

- `acquire_lock(key, ttl_seconds)`
  - `SET key value NX EX ttl` 风格锁。

- `release_lock(key)`
  - 删除锁 key。

- `save_cached_asset_content(...)`
  - 缓存图片 bytes。

- `load_cached_asset_content(asset_id)`
  - 读取图片 bytes cache。

阅读重点：

- Redis 在 reproduction 里只做锁，不做事实存储。
- 文件仍然是 reproduction run 的持久化来源。

### `src/integrations/llm/llms.py`

主要职责：

- OpenAI-compatible chat completions LLM provider。

关键类/方法：

- `OpenAICompatibleLLMConfig`

- `OpenAICompatibleLLMProvider`

- `generate(prompt)`
  - 非流式生成。

- `stream_generate(prompt)`
  - 流式生成文本 delta。

- `_build_payload(prompt, stream)`
  - 构造 chat completions payload。

- `_extract_stream_delta(data)`
  - 从 SSE data 中解析 delta。

阅读重点：

- 当前默认回答用 text prompt。
- vision image block 能力还没有作为默认执行路径接入。

## 8. 检索

### `src/usecases/retrieve_evidence.py`

主要职责：

- 编排完整证据检索流程。

关键类：

- `RetrieveEvidenceRequest`
  - 检索输入参数。

- `RetrieveEvidenceUseCase`
  - 检索主流程。

关键方法：

- `retrieve(query, project_id, document_limit, chunk_limit, asset_limit)`
  - 总入口。
  - 生成 query embedding。
  - 检索 documents。
  - 检索 chunks。
  - 检索 assets。
  - 构造 `EvidencePack`。
  - 写 debug log。

- `retrieve_documents(...)`
  - 同时查 title 和 summary。
  - 调用 `fuse_document_hits(...)`。
  - 可选 rerank。

- `retrieve_chunks(...)`
  - 在候选文档内检索 chunk。
  - 可选 rerank。
  - 做简单页面多样性过滤。

- `retrieve_assets(...)`
  - 在候选文档内检索 asset。
  - 当前查 summary 和 caption 两路。
  - 调用 `fuse_asset_hits(...)`。
  - 可选 rerank。

- `build_evidence_pack(...)`
  - 调用 `retrieval.evidence_pack.build_evidence_pack(...)`。

- `_append_debug_log(...)`
  - 把原始召回、融合、重排结果写入 JSONL，方便排查检索质量。

阅读重点：

- 先理解 `retrieve(...)` 的 pipeline。
- 再进入每个 retrieve_xxx 细节。
- 不要先读 rerank helper，容易迷路。

### `src/retrieval/fusion.py`

主要职责：

- 放纯函数融合逻辑。

关键函数：

- `fuse_document_hits(title_hits, summary_hits, limit)`
  - 文档级 title/summary 召回融合。

- `fuse_asset_hits(summary_hits, caption_hits=None, image_hits=None, limit)`
  - asset summary/caption/optional image 召回融合。

- `_fuse_weighted_hits(...)`
  - 通用加权融合。

阅读重点：

- 这是纯函数，最适合写单元测试。
- 当前 image hits 是可选输入，不是默认依赖。

### `src/retrieval/evidence_pack.py`

主要职责：

- 把检索命中组装成 `EvidencePack`。

关键函数：

- `build_evidence_pack(query, document_hits, chunk_hits, asset_hits)`
  - 生成正文 `Citation`。
  - 生成图片 `AssetCitation`。
  - 返回统一 `EvidencePack`。

阅读重点：

- `[C1]` 和 `[A1]` 这类引用最终依赖这里的顺序。

## 9. 生成回答

### `src/usecases/answer_question.py`

主要职责：

- 编排“检索证据 -> 构造 prompt -> 调用 LLM -> 流式返回事件”。

关键类：

- `AnswerStreamEvent`
  - SSE 事件对象。
  - 字段：`event`、`data`。

- `AnswerQuestionUseCase`

关键方法：

- `stream_answer(question, project_id, document_limit, chunk_limit, asset_limit)`
  - 调用 `retrieve_evidence_use_case.retrieve(...)`。
  - 构造 grounded prompt。
  - 先 yield `meta`。
  - 再流式 yield `delta`。
  - 最后 yield `done`，包含：
    - `answer`
    - `citations`
    - `asset_citations`
    - `asset_sources`

- `_build_prompt(question, evidence_pack, memory_summary="")`
  - 调用 prompt builder。

- `_serialize_citation(citation)`
  - 正文 citation 序列化。

- `_serialize_asset_citation(citation)`
  - 图片 citation 序列化。

- `_serialize_asset_source(hit)`
  - 生成图片展示源。
  - 关键字段：`asset_id`、`caption`、`summary`、`file_url`。

阅读重点：

- 默认不给大模型看图片，只给 caption/summary。
- 图片本身通过 `asset_sources.file_url` 交给 UI 展示。

### `src/generation/message_builders.py`

主要职责：

- 构造 grounded answer prompt。
- 构造可选 multimodal messages。

关键函数：

- `build_grounded_answer_prompt(question, evidence_pack, memory_summary="")`
  - 当前默认回答 prompt。
  - 包含 candidate documents、text evidence、visual evidence。
  - 要求文本引用 `[C1]`，视觉引用 `[A1]`。

- `build_multimodal_answer_messages(context, include_image_blocks=False)`
  - 可选 vision 模式消息构造。
  - 默认 `include_image_blocks=False`，只输出文本消息。
  - 开启后会把 image bytes 编成 data URL image block。

- `_build_multimodal_text_prompt(context)`
  - 把问题、文本证据、图片 metadata 构造成 XML-like prompt。

阅读重点：

- 默认生产链路主要看 `build_grounded_answer_prompt`。
- multimodal messages 是未来 vision 可选能力。

### `src/generation/multimodal_context.py`

主要职责：

- 构造短生命周期的多模态上下文对象。

关键 dataclass：

- `TextEvidenceItem`
- `ImageEvidenceItem`
- `MultimodalEvidenceContext`

关键函数：

- `build_multimodal_context(question, evidence_pack, asset_repository=None, max_images=4, load_image_bytes=False)`
  - 从 `EvidencePack` 生成 text_items 和 image_items。
  - 默认不加载 image bytes。
  - `load_image_bytes=True` 时才从 repository 或 file_path 读取图片 bytes。

阅读重点：

- 不要把 image bytes 放进 `EvidencePack`。
- image bytes 只应该在 generation 阶段短暂存在。

### `src/generation/citation_formatter.py`

主要职责：

- citation 序列化工具。

关键函数：

- `serialize_citation(citation)`
- `serialize_asset_citation(citation)`

阅读重点：

- API response 和 answer done event 都应复用这些格式，避免字段漂移。

## 10. LangGraph Orchestration

这一部分是当前后端最复杂的部分，建议最后读。

入口文件：

- `src/orchestration/supervisor.py`
- `src/orchestration/graph_state.py`
- `src/orchestration/graph_messages.py`
- `src/orchestration/output_summary.py`
- `src/workers/retriever/agent.py`
- `src/workers/tool/agent.py`
- `src/workers/workspace/agent.py`

### `src/orchestration/graph_state.py`

主要职责：

- 定义 LangGraph state。

阅读重点：

- 哪些字段在图节点之间传递。
- interrupt/resume 需要哪些状态。

### `src/orchestration/graph_messages.py`

主要职责：

- LangChain message 和前端 message 的转换。

阅读重点：

- 前端会话恢复时，消息如何序列化。

### `src/orchestration/supervisor.py`

主要职责：

- 构建 LangGraph。
- 准备上下文。
- 路由到 retriever/tool/workspace worker。
- 汇总 worker 输出。
- 处理中断和用户继续指导。

阅读建议：

1. 先看 graph 的节点有哪些。
2. 再看每个 node 的输入输出。
3. 最后看 worker 调用细节。

注意：

- 后续拆分时，目标是把独立 node/helper 移出这个文件。
- 不要轻易改变 LangGraph 行为。

## 11. 复现 Run

复现 run 是独立于普通聊天的长期任务系统。

### `api/routes/runs.py`

这部分前面 API 层已经讲过。它是复现 run 的 HTTP 入口。

### `src/workers/reproduce/models.py`

主要职责：

- 定义复现 run 的所有持久化状态模型。

关键 dataclass：

- `PlanTask`
  - DAG 中的一个任务。
  - 关键字段：`task_id`、`task_type`、`status`、`assigned_to`、`blocked_by`、`artifact_ids`。

- `AgentState`
  - worker 状态。

- `Artifact`
  - 生成文件、日志、报告等产物。

- `MailboxMessage`
  - agent 之间的 mailbox 消息。

- `RunEvent`
  - run 事件。

- `ReproductionRun`
  - 整个复现 run 的状态。
  - 关键字段：`run_id`、`status`、`tasks`、`artifacts`、`events`、`workspace_path`、`report_path`。

关键函数：

- `ReproductionRun.create(...)`
  - 创建 run。
  - 自动生成初始 DAG。

- `build_initial_tasks()`
  - 固定初始 DAG：
    - T1 understand_paper
    - T2 extract_method
    - T3 inspect_figures
    - T4 design_reproduction
    - T5 create_project_files
    - T6 run_experiment
    - T7 analyze_results
    - T8 write_report

### `src/workers/reproduce/store.py`

主要职责：

- 文件持久化 run 状态。

关键类/方法：

- `FileReproductionStore`

- `create(run)`
  - 创建 run 目录、workspace、logs 目录。

- `load(run_id)`
  - 从 `run.json` 读取 run。

- `save(run)`
  - 先写 `run.json.tmp`，再 replace。
  - 避免写到一半损坏主文件。

- `list_runs(project_id=None)`
  - 列出 run。

- `append_event(run_id, event)`
  - 追加事件。

阅读重点：

- 文件是事实存储。
- Redis 不是事实存储。

### `src/workers/reproduce/mailbox.py`

主要职责：

- 文件 JSONL mailbox。

关键类/方法：

- `FileMailbox`

- `ensure_mailboxes(run_id, agent_names)`
  - 为每个 agent 创建 jsonl 文件。

- `send(...)`
  - 追加一条 message 到 recipient mailbox。
  - 如果配置了 lock，会先拿 mailbox lock。

- `read_unread(run_id, agent_name)`
  - 读取未读消息。

- `mark_read(run_id, agent_name, message_ids)`
  - 将指定消息标记为 read。
  - 会重写该 agent 的 jsonl 文件。

阅读重点：

- mailbox 是文件实现，便于调试。
- lock 只是保护并发写，不改变存储方式。

### `src/workers/reproduce/locks.py`

主要职责：

- 可选 Redis lock 适配器。

关键类：

- `NullReproductionLock`
  - 无 Redis 时使用。
  - 所有锁操作都是 no-op。

- `RedisReproductionLock`
  - 包装 `RedisCacheStore.acquire_lock/release_lock`。

关键方法：

- `acquire_run(run_id)`
  - 获取 run 锁。

- `release_run(run_id)`
  - 释放 run 锁。

- `mailbox_lock(run_id, agent_name)`
  - mailbox 写入/mark_read 的上下文锁。

阅读重点：

- run 锁避免两个后台任务同时推进同一个 run。
- mailbox 锁避免 JSONL 文件并发写坏。

### `src/workers/reproduce/plan_agent.py`

主要职责：

- 推进复现 run 的 DAG。

关键类/方法：

- `PlanAgent`

- `create_run(project_id, objective, paper_ids, permission_mode="manual")`
  - 创建 `ReproductionRun`。
  - 创建 workspace。
  - 创建 mailboxes。
  - 保存 run。

- `run(run_id)`
  - 获取 run lock。
  - 循环推进 DAG：
    - 读取 worker result。
    - 找 ready tasks。
    - 发 task_assignment。
    - tick worker。
    - 保存状态。
  - 所有任务完成后标记 completed。

- `_apply_worker_results(run)`
  - 读取 plan_agent mailbox。
  - 根据 task_result 更新 task 状态和 artifact ids。

- `_ready_tasks(run)`
  - 找出所有 pending 且依赖已完成的任务。

- `_worker_for_task(task_type)`
  - 根据任务类型选择固定 worker。

阅读重点：

- 当前是固定初始 DAG。
- 未来可以追加 repair/follow-up task，但不动态创建 worker。

### `src/workers/reproduce/workers.py`

主要职责：

- 固定 worker 实现。

关键类：

- `BaseWorker`
  - `tick(run)` 读取自己的 mailbox。
  - `handle_task(...)` 由子类实现。
  - `complete(...)` 给 plan_agent 发 task_result。

- `MethodWorker`
  - `understand_paper`
  - `extract_method`

- `FigureWorker`
  - `inspect_figures`

- `CodeWorker`
  - `design_reproduction`
  - `create_project_files`
  - 写 `README.md`、`requirements.txt`、`reproduce.py`

- `ExperimentWorker`
  - `run_experiment`
  - `analyze_results`
  - 执行 `python reproduce.py`
  - 写 `outputs/logs/run_experiment.log`

- `ReportWorker`
  - `write_report`
  - 写 `report.md`

- `build_default_workers(...)`
  - 创建固定 worker 列表。

阅读重点：

- worker 当前是 scaffold 级别。
- 后续提升质量时，应该让 worker 消费 EvidencePack。

### `src/workers/reproduce/command_policy.py`

主要职责：

- 确定性命令安全策略。

关键类/方法：

- `CommandPolicyResult`
  - `decision`: `allow` / `deny` / `require_user`
  - `reason`

- `CommandPolicy.decide(command, cwd, workspace_path)`
  - cwd 必须在 workspace 内。
  - 明确危险命令直接 deny。
  - 明确安全命令 allow。
  - 其它命令 require_user。

阅读重点：

- 确定性 deny 不能被 LLM 推翻。
- 这层是阶段三安全边界的核心。

相关测试：

```bash
uv run pytest tests/test_reproduce_core.py tests/test_reproduce_locks.py -q
```

## 12. 测试怎么对应代码

建议用测试反向学习代码。

### `tests/test_entrypoints.py`

覆盖：

- `api.main` 能 import。
- `/healthz` 可用。
- `/chat/state` 可用。
- 文件夹选择 endpoint 可用。

适合学习：

- API app 如何启动。

### `tests/test_phase_boundaries.py`

覆盖：

- domain 旧 import 兼容。
- route 模块已经有实际路径。
- retrieval/generation 基础边界。
- reproduce/workspace 目录存在。

适合学习：

- 目录拆分后哪些兼容性必须保留。

### `tests/test_indexing_and_assets.py`

覆盖：

- `AssetIndexer` 写 caption/summary/optional image vectors。
- asset 检索融合 summary + caption。
- answer done event 带 `asset_sources`。

适合学习：

- 图片证据链路。

### `tests/test_reproduce_core.py`

覆盖：

- reproduction run dataclass 序列化。
- file store 保存和读取。
- mailbox send/read/mark_read。
- command policy。
- PlanAgent smoke run。

适合学习：

- 复现 run 的核心流程。

### `tests/test_reproduce_locks.py`

覆盖：

- mailbox 写入使用可选 lock。
- run lock 被占用时 PlanAgent 不重复推进。

适合学习：

- Redis lock 接入方式。

## 13. 推荐学习顺序

按这个顺序读，效率最高：

1. `api/main.py`
2. `api/dependencies.py`
3. `api/routes/documents.py`
4. `api/routes/ingestion.py`
5. `src/domain/models.py`
6. `src/domain/ports.py`
7. `src/usecases/ingest_document.py`
8. `src/indexing/*`
9. `src/usecases/retrieve_evidence.py`
10. `src/retrieval/*`
11. `src/usecases/answer_question.py`
12. `src/generation/*`
13. `api/routes/runs.py`
14. `src/workers/reproduce/*`
15. `src/orchestration/supervisor.py`

每读完一块，跑对应测试。不要只看代码不跑测试。

## 14. 推荐修改顺序

如果你要自己改功能，建议：

1. 小改 API route
   - 先改 `api/routes/*`
   - 再改 `api/schemas.py`
   - 跑 `tests/test_entrypoints.py`

2. 改入库逻辑
   - 先看 `IngestDocumentUseCase`
   - 具体索引逻辑放 `src/indexing/*`
   - 跑 `tests/test_indexing_and_assets.py`

3. 改检索逻辑
   - 纯融合逻辑放 `src/retrieval/fusion.py`
   - EvidencePack 组装放 `src/retrieval/evidence_pack.py`
   - 跑 `tests/test_indexing_and_assets.py`

4. 改回答格式
   - prompt 改 `src/generation/message_builders.py`
   - event 字段改 `src/usecases/answer_question.py`
   - schema 同步改 `api/schemas.py`

5. 改复现 run
   - 状态模型改 `models.py`
   - 持久化改 `store.py`
   - 调度改 `plan_agent.py`
   - worker 行为改 `workers.py`
   - 安全策略改 `command_policy.py`

6. 最后再改 LangGraph supervisor
   - 先补测试。
   - 只拆独立 helper/node。
   - 不要顺手改变图行为。

## 15. 常用验证命令

API 基础：

```bash
uv run pytest tests/test_entrypoints.py tests/test_phase_boundaries.py -q
```

入库、索引、图片证据：

```bash
uv run pytest tests/test_indexing_and_assets.py -q
```

复现 run：

```bash
uv run pytest tests/test_reproduce_core.py tests/test_reproduce_locks.py -q
```

完整后端：

```bash
uv run pytest -q
```

## 16. 当前后端还值得继续完善的点

1. 拆 `orchestration/supervisor.py`
   - 目标是按 node/helper 拆。
   - 不改 LangGraph 行为。

2. 让 reproduction worker 消费真实 EvidencePack
   - `MethodWorker` 用正文 chunks。
   - `FigureWorker` 用 asset captions/summaries。
   - `ReportWorker` 输出 Used evidence。

3. 增强 command policy
   - 区分 Bash 和 PowerShell。
   - 更细地处理网络下载、pip install、文件删除。

4. 可选 vision 模式
   - 仅当配置开启且 provider 支持 image blocks 时启用。

5. 项目 id 统一
   - 当前某些 document route 仍使用 `frontend-project`。
   - 后续可以让 API payload 显式传 project_id。
