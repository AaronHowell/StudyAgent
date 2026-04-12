# StudyAgent 人类可读手册

这份手册不按代码文件讲，而按“系统如何工作”来讲。  
目标是让你在阅读代码之前，先知道：

- 系统里有哪些核心数据对象
- 每个对象的字段是什么意思
- 一篇 PDF 从被发现到进入数据库，中间到底经历了什么
- 当前已经实现到什么程度，哪些地方只是第一版

---

## 1. 系统当前在做什么

当前 StudyAgent 已经完成的是一条“文档入库底座”：

1. 扫描本地目录里的 PDF
2. 为每篇 PDF 建立文档记录
3. 解析 PDF 的标题、页文本、视觉资产
4. 把正文切成 chunk
5. 写入 MySQL
6. 写入 Qdrant
7. 给前端展示文档列表、阅读页面、画廊和入库任务状态
8. 提供第一版 retrieval evidence API

它还没有完成的是：

- 长短期记忆
- 多 Agent 拆分编排
- Web retrieval / hybrid retrieval

所以你现在可以把项目理解成：

**一个已经具备“文档解析 + 结构化入库 + retrieval + LangGraph 单 Agent 问答”的科研论文工作台。**

---

## 2. 核心模型说明

这些模型主要定义在：

`packages/domain/src/study_agent_domain/models.py`

### 2.1 `Project`

表示一个研究项目。

字段：
- `id`
  - 项目唯一标识
- `name`
  - 项目名称
- `root_path`
  - 这个项目绑定的本地文档目录
- `description`
  - 项目描述

作用：
- 给文档、检索、记忆提供作用域

---

### 2.2 `Document`

表示系统里的一篇源文档。

字段：
- `id`
  - 文档唯一标识
- `project_id`
  - 这篇文档属于哪个项目
- `path`
  - 本地绝对路径
- `file_name`
  - 文件名
- `doc_type`
  - 文档类型，目前主要是 `pdf`
- `title`
  - 文档标题，优先来自 PDF 元数据或首页文本
- `status`
  - 当前状态：
    - `discovered`
    - `indexed`
    - `failed`
- `content_hash`
  - 文件内容 hash，用来判断文档是否变化

作用：
- 是整篇论文在系统里的主记录

---

### 2.3 `PdfPage`

表示一页 PDF 的文本结果。

字段：
- `page_number`
  - 页码
- `text`
  - 当前页提取到的整页文本
- `metadata`
  - 附加信息，比如字符数、来源路径

作用：
- 是 PDF 解析层的中间对象
- 给标题提取、图注识别、chunk 构建提供输入

说明：
- `PdfPage` 通常不会作为最终知识单元直接给 Agent 用
- 最终更重要的是 `Chunk`

---

### 2.4 `DocumentAsset`

表示从论文里提取出来的视觉资产。

它统一表示：
- 图
- 表
- 流程图
- 架构图
- 通过页面区域渲染得到的视觉区域

字段：
- `id`
  - 视觉资产唯一标识
- `document_id`
  - 属于哪篇论文
- `page_number`
  - 位于第几页
- `file_path`
  - 导出图片缓存路径
- `file_name`
  - 图片缓存文件名
- `asset_kind`
  - 资产类别，常见值：
    - `figure`
    - `table`
    - `visual`
- `asset_label`
  - 资产标签，例如：
    - `Figure 3`
    - `Table 5`
- `asset_index`
  - 标签里的编号，例如 `3`
- `caption`
  - 图注或表题
- `summary`
  - 轻量摘要
- `asset_type`
  - 粗粒度类型，例如：
    - `table`
    - `architecture_diagram`
    - `result_plot`
    - `workflow_diagram`
- `keywords`
  - 关键词
- `related_chunk_ids`
  - 相关正文 chunk，当前只是预留，后续要真正建立
- `media_type`
  - 资源类型，例如 `image/png`
- `metadata`
  - 附加字段，例如页码、渲染方式、bbox 等

兼容属性：
- `figure_label`
- `figure_index`

作用：
- 作为视觉证据对象参与检索和后续问答

---

### 2.5 `Chunk`

表示正文里的一个文本知识块。

字段：
- `id`
  - chunk 唯一标识
- `project_id`
  - 所属项目
- `document_id`
  - 所属文档
- `chunk_index`
  - 在文档中的顺序编号
- `chunk_type`
  - 当前主要是 `text`
- `text`
  - chunk 正文文本
- `page`
  - 来源页码
- `section`
  - 所属章节，当前大多为空
- `metadata`
  - 其它附加信息

作用：
- 是正文检索的核心单位
- 后续回答时引用的主要证据来源

---

### 2.6 `DocumentProfile`

表示一篇论文的“检索画像”。

字段：
- `document_id`
- `project_id`
- `title`
- `summary`
- `keywords`
- `file_name`
- `path`
- `metadata`

作用：
- 它不是原始解析对象
- 它是在入库阶段生成的文档级检索对象
- 用于先从整库里找相关论文，再缩小到正文和图表

你可以把它理解成：

**给每篇论文做的一张检索名片**

---

### 2.7 `Citation`

表示一个回到原始来源的轻量引用。

字段：
- `document_id`
- `document_title`
- `chunk_id`
- `page`
- `locator`

作用：
- 后续 Retrieval / Writer 阶段给回答附引用

---

### 2.8 `EvidencePack`

表示一轮检索组装出来的证据包。

字段：
- `query`
- `documents`
- `text_chunks`
- `assets`
- `image_chunks`
- `web_snippets`
- `citations`

作用：
- 是后续 Retrieval Agent -> Writer Agent 之间的核心中间结构

说明：
- 当前已经有第一版真实实现
- 当前主要使用：
  - `documents`
  - `text_chunks`
  - `assets`
  - `citations`
- `image_chunks` 和 `web_snippets` 仍然保留为后续多模态 / web retrieval 预留字段

---

### 2.9 `ScoredId`

表示向量检索阶段返回的轻量命中对象。

字段：
- `entity_id`
- `score`

作用：
- 在 Qdrant 检索后先返回“id + 分数”
- 然后再回 MySQL 拿完整对象

---

### 2.10 `DocumentHit`

表示文档级命中。

字段：
- `document`
- `score`

作用：
- 表示一篇候选论文以及它对当前 query 的相关度

---

### 2.11 `ChunkHit`

表示正文 chunk 命中。

字段：
- `chunk`
- `score`

作用：
- 表示一段正文证据以及它对当前 query 的相关度

---

### 2.12 `AssetHit`

表示视觉资产命中。

字段：
- `asset`
- `score`

作用：
- 表示一个图、表或视觉区域证据以及它对当前 query 的相关度

---

## 3. 数据存在哪里

### 3.1 MySQL

MySQL 存结构化元数据和原文内容。

当前表：
- `projects`
- `documents`
- `document_assets`
- `chunks`

职责：
- 持久化文档、资产、chunk 的完整结构化信息
- 给前端展示和后续引用回查提供真相源

### 3.2 Qdrant

Qdrant 存向量索引。

当前 collection：
- `study_agent_documents`
- `study_agent_chunks`
- `study_agent_assets`

职责：
- 做语义召回

分层意义：
- `documents`
  - 先找相关论文
- `chunks`
  - 再找正文证据
- `assets`
  - 再找图表证据

### 3.3 文件系统缓存

当前视觉资产导出的图片缓存保存在：

- `StudyAgentCache/pdf_images`

职责：
- 给前端画廊预览
- 给后续需要看图的模型提供原始资源入口

---

## 4. 文档扫描是怎么做的

扫描逻辑主要在：

`packages/documents/src/study_agent_documents/document_scan.py`

### 扫描阶段做什么

1. 遍历目录
2. 过滤无关目录
3. 找到支持的文件类型
4. 计算文件 hash
5. 构造 `Document`

### 当前支持的文件类型

主要支持：
- `.pdf`
- `.md`
- `.markdown`

### 扫描输出

扫描输出不是直接入库，而是先得到：
- `Document`
- `ScanSummary`

也就是说，扫描阶段先回答的是：

- 目录里有哪些文档
- 每篇文档的基础元信息是什么

---

## 5. PDF 是怎么解析的

解析逻辑主要在：

`packages/documents/src/study_agent_documents/pdf_parser.py`

### 5.1 元数据解析

优先级：
1. PDF metadata 里的标题
2. 首页文本启发式标题
3. 文件名回退

作者、页数等也会一起提出来。

### 5.2 页文本解析

当前做法：
- 使用 `pypdf` 逐页提取文本
- 做基础清洗
- 生成 `PdfPage`

输出：
- 每页一个 `PdfPage`
- `text` 是整页文本

### 5.3 视觉资产解析

当前策略是混合式：

#### 第一层：embedded image 提取

用 `PyMuPDF`：
- 找页面里的图片对象
- 直接提图
- 如果提取结果明显坏，就不直接信它

#### 第二层：坏图回退区域渲染

如果直接提图结果：
- 全黑
- 全白
- 透明层错乱
- 明显不可信

就用区域渲染替代。

#### 第三层：caption 锚点区域渲染

这是当前针对 LaTeX / TikZ / 矢量图的关键优化。

做法：
1. 先从页文本里找：
   - `Figure N`
   - `Fig. N`
   - `Table N`
   - `图 N`
   - `表 N`
2. 再在页面文本块里找 caption 的位置
3. 根据 caption 位置推断一个视觉区域
4. 直接把这块页面渲染成 PNG

这个策略的意义是：

**就算 PDF 里没有真正的图片对象，也能提取出视觉资产。**

这对：
- LaTeX 直接绘图
- TikZ 图
- 表格
- 矢量图

特别重要。

---

## 6. 文本是怎么分块的

分块逻辑主要在：

`packages/documents/src/study_agent_documents/chunking.py`

### 为什么要分块

因为：
- 整篇论文太长，不能直接做 embedding
- 检索也需要更细粒度单位
- 后续引用需要页级或段落级证据

### 当前分块流程

1. 按页处理
2. 按双换行拆自然段
3. 合并过短段落
4. 按 chunk 预算打包
5. 对超长段落再拆分
6. 生成 `Chunk`

### 当前分块控制逻辑

当前不再主要按字符数切，而是按**近似 token 预算**切。

默认参数：
- `max_approx_tokens = 420`
- `overlap_approx_tokens = 64`

同时保留字符兜底：
- `max_chars = 1800`
- `overlap_chars = 240`

### 为什么这么做

因为你的 embedding 模型上下文上限比较小，最大大约 `512 tokens`。

如果 chunk 本身太大，就会出现：
- 入向量库前被硬截断
- 后半段语义丢失

所以现在的策略是：

**尽量在 chunk 阶段就把文本切到适合 embedding 的范围。**

---

## 7. 文档是怎么入库的

入库主流程在：

`packages/application/src/study_agent_application/ingest_document_use_case.py`

### `IngestDocumentUseCase` 做什么

它是单篇文档入库的总协调器。

输入：
- 一篇文档路径或一个 `Document`

输出：
- `IngestDocumentResult`

### 它串起来的步骤

1. 检查路径
2. 计算 `content_hash`
3. 创建 `Document`
4. 解析 PDF
5. 生成 `DocumentAsset`
6. 生成 `Chunk`
7. 写 MySQL
8. 生成 `DocumentProfile`
9. 做 embedding
10. 写 Qdrant

### 跳过重复入库

当前有基础去重逻辑：
- 同路径
- 同 `project_id`
- 同 `content_hash`
- 且文档状态已是 `indexed`

则直接返回：
- `skipped`

### 更新已有文档

如果同路径文件内容变了：
- 重新解析成功后
- 删除旧 chunk / asset / document
- 再写新版本

返回：
- `updated`

---

## 8. 向量是怎么生成和写入的

### 8.1 Embedding Provider

当前实现：

`packages/integrations/src/study_agent_integrations/embeddings.py`

做法：
- 调 OpenAI-compatible `/embeddings`

当前会对输入文本做：
- 空白归一化
- 近似 token 裁剪

原因：
- 你的 embedding 模型最大 tokens 约 `512`
- 当前默认保护值是 `480`

### 8.2 Qdrant 写入

当前写三层：

#### 文档级
- `DocumentProfile.title`
- `DocumentProfile.summary`

#### chunk 级
- `content`
- `title`
- `summary`

#### asset 级
- `caption`
- `summary`

也就是说，当前视觉资产入向量库靠的是：
- 图注
- 摘要

不是真正的图片 embedding。

---

## 9. 前端当前能做什么

前端在：

`apps/desktop`

当前已完成：
- 扫描目录
- 文档表格
- 显示是否已入库
- 单篇入库
- 批量入库
- 入库任务状态
- PDF 阅读页面
- 视觉资产画廊

还没完成：
- retrieval 界面
- 文档级 / chunk / asset 检索面板
- Agent 聊天主链

---

## 10. API 当前能做什么

主要 API：

- `POST /documents/scan`
- `POST /documents/images`
- `POST /documents/ingestion-status`
- `POST /documents/ingest`
- `GET /documents/ingest/{task_id}`
- `GET /documents/ingest`
- `POST /documents/ingest/batch`
- `GET /documents/file`
- `POST /retrieval/evidence`

你可以这样理解：

- `/documents/scan`
  - 找文档
- `/documents/images`
  - 看图表
- `/documents/ingest`
  - 入库
- `/documents/ingest*`
  - 查任务状态
- `/documents/file`
  - 给前端预览 PDF 和图片
- `/retrieval/evidence`
  - 返回可直接消费的 `EvidencePack`

---

## 11. Retrieval 是怎么做的

Retrieval 主流程现在在：

`packages/application/src/study_agent_application/retrieve_evidence_use_case.py`

这是第一版真实可运行的 Retrieval 编排层。

### 11.1 数据流总览

当前 retrieval 数据流是：

```text
User Query
  -> embed query
  -> document retrieval in Qdrant (title + summary)
  -> fuse document hits
  -> cross-encoder rerank documents
  -> candidate document ids
  -> chunk retrieval in Qdrant
  -> cross-encoder rerank chunks
  -> chunk dedupe
  -> asset retrieval in Qdrant
  -> cross-encoder rerank assets
  -> asset dedupe
  -> batch hydrate from MySQL
  -> build EvidencePack
  -> append one JSONL debug log row
  -> return API response
```

也就是说，现在的 retrieval 不是全局混搜，而是：

1. 先用 `study_agent_documents` 的 `title` 和 `summary` 两套 named vector 找候选论文
2. 再把候选 `document_id` 作为过滤条件，去 `study_agent_chunks` 找正文证据
3. 再把同一批候选 `document_id` 作为过滤条件，去 `study_agent_assets` 找图表证据
4. 对 documents / chunks / assets 做 cross-encoder 重排
5. 对 chunk / asset 做轻量去重
6. 最后把三层结果组装成 `EvidencePack`
7. 把原始召回和最终结果写入统一 JSONL debug log

### 11.2 为什么要这样做

这样做有三个直接好处：

1. 先缩小候选论文，能减少 chunk 和 asset 级误召回
2. `title + summary` 融合比只查一个向量槽更稳
3. cross-encoder 能对 top-k 候选做更精细的 query-aware 语义比较
4. chunk 和 asset 能共享同一个候选文档集合，证据更集中
5. 去重能减少重复页、空 caption 这类低质量命中
6. JSONL debug log 让你能回看每次召回质量，而不用额外做前端调试面板

### 11.3 核心函数说明

下面这些函数是 retrieval 第一版的主干。

#### `RetrieveEvidenceUseCase.retrieve`

作用：
- retrieval 的总入口
- 负责把一次 query 的完整三层检索串起来

输入：
- `query`
  - 用户问题文本
- `project_id`
  - 检索范围所属项目
- `document_limit`
  - 文档级命中上限
- `chunk_limit`
  - chunk 级命中上限
- `asset_limit`
  - asset 级命中上限

输出：
- `EvidencePack`

具体实现：
1. 先对 `query` 做一次 embedding
2. 调 `retrieve_documents`
3. 从文档命中里提取候选 `document_id`
4. 调 `retrieve_chunks`
5. 调 `retrieve_assets`
6. 调 `build_evidence_pack` 返回统一结果

#### `RetrieveEvidenceUseCase.retrieve_documents`

作用：
- 先从文档级画像里找相关论文

输入：
- `query`
- `project_id`
- `query_vector`
  - 可选，传入时可复用已算好的 query embedding
- `limit`

输出：
- `list[DocumentHit]`

具体实现：
1. 如果外部没传 `query_vector`，内部先算 embedding
2. 分别调两次 `vector_store.search_documents(...)`
3. 一次查 `title`
4. 一次查 `summary`
5. 把两路结果做融合排序
6. 调 `document_repository.list_by_ids(...)`
7. 如果配置了 reranker，再对候选文档做 cross-encoder 重排
8. 按重排后的顺序组装成 `DocumentHit`

#### `RetrieveEvidenceUseCase.retrieve_chunks`

作用：
- 在候选论文范围内找正文证据

输入：
- `query`
- `project_id`
- `document_ids`
- `query_vector`
- `limit`

输出：
- `list[ChunkHit]`

具体实现：
1. 如果候选 `document_ids` 为空，直接返回空列表
2. 调 `vector_store.search_chunks(...)`
3. 检索时用 `document_ids` 作为过滤条件
4. Qdrant 返回 `list[ScoredId]`
5. 调 `chunk_repository.list_by_ids(...)`
6. 组装成 `ChunkHit`
7. 如果配置了 reranker，先对 chunk 文本做 cross-encoder 重排
8. 再做轻量去重：
   - 同一文档相邻页的重复 chunk 会被去重

补充说明：
- 当前 embedding 检索仍然使用较小的原始 chunk
- 这样能保持召回粒度细、向量成本低
- 但 chunk rerank 阶段会把命中 chunk 作为中心，拼接相邻 chunk 再送给 cross-encoder
- 这样做是为了吃到 reranker 更大的上下文窗口
- 最终 citation 仍然指向中心 chunk，而不是指向拼接后的临时文本

#### `RetrieveEvidenceUseCase.retrieve_assets`

作用：
- 在候选论文范围内找图表或视觉证据

输入：
- `query`
- `project_id`
- `document_ids`
- `query_vector`
- `limit`

输出：
- `list[AssetHit]`

具体实现：
1. 如果候选 `document_ids` 为空，直接返回空列表
2. 调 `vector_store.search_assets(...)`
3. 检索时用 `document_ids` 作为过滤条件
4. Qdrant 返回 `list[ScoredId]`
5. 调 `asset_repository.list_by_ids(...)`
6. 组装成 `AssetHit`
7. 如果配置了 reranker，先对 `caption / summary / asset_type` 文本做 cross-encoder 重排
8. 再做轻量去重：
   - `caption` 和 `summary` 都很空的资产直接过滤
   - 同页同标签重复资产会被去重

#### `RetrieveEvidenceUseCase.build_evidence_pack`

作用：
- 把三层命中整理成统一证据包

输入：
- `query`
- `document_hits`
- `chunk_hits`
- `asset_hits`

输出：
- `EvidencePack`

具体实现：
1. 先建立 `document_id -> title` 映射
2. 遍历 `chunk_hits`
3. 为每个 chunk 生成一条 `Citation`
4. `locator` 当前用页码格式，例如 `p.8`
5. 返回包含 `documents`、`text_chunks`、`assets`、`citations` 的 `EvidencePack`

#### `RetrieveEvidenceUseCase._append_debug_log`

作用：
- 把一次 retrieval 的关键中间结果写入 JSONL 日志

输入：
- `query`
- `project_id`
- `raw_document_hits`
- `raw_chunk_hits`
- `raw_asset_hits`
- `evidence_pack`

输出：
- 无返回值

具体实现：
1. 如果没配置 `debug_log_path`，直接跳过
2. 自动创建日志目录
3. 每次 retrieval 追加写入一行 JSON
4. 当前一条日志至少包含：
   - 时间戳
   - query
   - 原始文档召回
   - reranked 文档结果
   - 原始 chunk 召回
   - 原始 asset 召回
   - 最终保留的 documents / text_chunks / assets
   - citations

### 11.4.1 Cross-Encoder 重排是怎么接入的

当前使用的是可选 `RerankerProvider`。

作用：
- 在向量召回后的候选集合上做第二阶段重排

当前接入方式：
- API 启动时按 config 创建远程 reranker provider
- `RetrieveEvidenceUseCase` 只依赖 `RerankerProvider`
- 如果没启用 reranker，就直接退回向量排序结果

当前重排位置：
- document retrieval 融合后
- chunk retrieval 回填后
- asset retrieval 回填后

当前默认配置值：
- `retrieval_reranker_enabled = false`
- `retrieval_document_recall_k = 12`
- `retrieval_chunk_recall_k = 20`
- `retrieval_asset_recall_k = 12`
- `retrieval_chunk_rerank_neighbor_window = 1`

含义：
- `recall_k`
  - 向量召回阶段先取多少候选
- `top_k`
  - 最终保留多少结果

当前 `top_k` 来源：
- 文档级：`document_limit`
- chunk 级：`chunk_limit`
- asset 级：`asset_limit`

推荐起始值：
- `document_recall_k = 12`
- `document_limit = 5`
- `chunk_recall_k = 20`
- `chunk_limit = 8`
- `asset_recall_k = 12`
- `asset_limit = 6`
- `chunk_rerank_neighbor_window = 1`

为什么这么配：
- 先给 reranker 足够候选空间
- 又不至于让远程 rerank 请求过大
- `neighbor_window = 1` 表示：
  - 对每个命中 chunk，拼接 `前 1 + 当前 1 + 后 1`
  - 总共最多 3 个 chunk 的文本一起参与 rerank

### 11.5 向量层函数说明

Qdrant 适配器在：

`packages/integrations/src/study_agent_integrations/qdrant_store.py`

#### `search_documents`

作用：
- 在 `study_agent_documents` collection 里检索候选论文

输入：
- `query_vector`
- `project_id`
- `vector_name`
- `limit`

输出：
- `list[ScoredId]`

实现说明：
- 当前 retrieval 质量增强后会同时走：
  - `title`
  - `summary`
- 用 `project_id` 做过滤

#### `search_chunks`

作用：
- 在 `study_agent_chunks` collection 里检索正文 chunk

输入：
- `query_vector`
- `project_id`
- `vector_name`
- `document_ids`
- `limit`

输出：
- `list[ScoredId]`

实现说明：
- 当前默认走 `content` named vector
- 当传入 `document_ids` 时，会把它加入 Qdrant filter

#### `search_assets`

作用：
- 在 `study_agent_assets` collection 里检索视觉资产

输入：
- `query_vector`
- `project_id`
- `vector_name`
- `document_ids`
- `limit`

输出：
- `list[ScoredId]`

实现说明：
- 当前默认走 `summary` named vector
- 当传入 `document_ids` 时，会把它加入 Qdrant filter

### 11.6 MySQL 回填函数说明

为支持 retrieval 命中批量回填，MySQL repository 现在新增了三类批量查询：

- `document_repository.list_by_ids(document_ids)`
- `chunk_repository.list_by_ids(chunk_ids)`
- `asset_repository.list_by_ids(asset_ids)`

作用：
- 用命中的 id 列表回查完整对象

输入：
- 一组业务 id

输出：
- 对应对象列表

实现说明：
- 使用 SQL `IN (...)` 批量读取
- 然后由应用层按 Qdrant 返回顺序重新组装，避免 SQL 自己打乱相关度顺序

### 11.7 Retrieval API 说明

入口：

- `POST /retrieval/evidence`

请求输入：
- `query`
- `project_id`
- `document_limit`
- `chunk_limit`
- `asset_limit`

响应输出：
- `query`
- `documents`
- `text_chunks`
- `assets`
- `citations`

实现说明：
- API 层本身不做检索逻辑
- API 只负责：
  - 参数校验
  - 调用 `RetrieveEvidenceUseCase`
  - 把 `EvidencePack` 序列化成 HTTP 响应
- 如果 embedding provider 或 Qdrant 没配置，接口会返回 `503`

### 11.8 Retrieval Debug Log 说明

当前 retrieval debug log 默认写到：

- `logs/retrieval-debug.jsonl`

也可以通过环境变量覆盖：

- `STUDY_AGENT_RETRIEVAL_DEBUG_LOG_PATH`

为什么用 JSONL：
- 每次请求一行，适合持续追加
- 好 grep
- 好做后续脚本分析
- 不需要专门建表

当前推荐用途：
- 看文档级融合后是否更稳定
- 看 cross-encoder 是否把正确候选提到前面
- 看 chunk 是否被相邻页重复命中挤占
- 看 asset 是否被空 caption 噪声污染
- 判断问题出在 retrieval 还是后续 Agent / Writer

---

## 12. Agent 编排是怎么做的

当前正式问答主链已经迁移到 LangGraph 风格运行时。

核心位置：

- `packages/agents/src/study_agent_agents/graph.py`
- `packages/agents/src/study_agent_agents/runtime.py`
- `langgraph.json`

保留的旧接口：

- `packages/application/src/study_agent_application/answer_question_use_case.py`
- `POST /agent/answer/stream`

也就是说，现在系统有两条问答路径：

1. LangGraph Agent Server 风格主链
2. 旧的自定义 SSE 接口，作为兼容和调试入口继续保留

### 12.1 LangGraph Agent 数据流

```text
Frontend useStream
  -> LangGraph Agent Server
  -> retrieve_evidence_node
  -> RetrieveEvidenceUseCase
  -> grounded_prompt
  -> answer_question_node
  -> ChatOpenAI (OpenAI-compatible)
  -> LangGraph message stream
  -> assistant-ui runtime
  -> Frontend incremental rendering
```

### 12.2 `study_agent_agents.graph`

这个 graph 目前还是单 Agent，不是 Planner / Critic / Memory 多节点系统。

当前节点只有两个：

1. `retrieve_evidence_node`
2. `answer_question_node`

作用：
- 把 retrieval 和 generation 拆成两个清晰阶段
- 同时保留 `project_id`、top-k 和 citation 元数据

### 12.3 `retrieve_evidence_node`

作用：
- 从 LangGraph 的 `messages` 里取最后一条 user message
- 读取 `configurable.project_id`
- 调用 `RetrieveEvidenceUseCase`
- 产出 grounded prompt、citation 元数据和 evidence 计数

输入：
- `state.messages`
- `config.configurable.project_id`
- `config.configurable.document_limit`
- `config.configurable.chunk_limit`
- `config.configurable.asset_limit`

输出：
- `citations`
- `evidence_counts`
- `grounded_prompt`

### 12.4 `answer_question_node`

作用：
- 把 retrieval 产出的 grounded prompt 交给 LangChain `ChatOpenAI`
- 把最终回答写回 `messages`
- 同时把 citations 写进 assistant message metadata

输入：
- `grounded_prompt`
- `citations`
- `evidence_counts`

输出：
- `messages`

实现说明：
- 这里直接复用了 OpenAI-compatible LLM 配置
- 因为模型调用已经放进 LangGraph 节点里，所以前端能通过 `useStream` 直接消费 LangGraph message stream

### 12.5 LangGraph 配置文件

当前 LangGraph 入口配置在：

- `langgraph.json`

作用：
- 声明本地 Agent Server 要加载哪个 graph
- 指向 `.env`

当前 graph id：

- `study_agent`

当前关键环境变量：

- `STUDY_AGENT_LANGGRAPH_ASSISTANT_ID`
- `STUDY_AGENT_DEFAULT_PROJECT_ID`
- `VITE_STUDY_AGENT_LANGGRAPH_API_URL`
- `VITE_STUDY_AGENT_LANGGRAPH_ASSISTANT_ID`

### 12.6 前端聊天运行时

前端当前已经不再手动解析自定义 SSE，而是改成：

- `@langchain/react` 的 `useStream`
- `@assistant-ui/react` 的 runtime / primitives

主要实现位置：

- `apps/desktop/src/StudyAgentChatPanel.tsx`
- `apps/desktop/src/App.tsx`

实现说明：
- `useStream` 直接连 LangGraph Agent Server
- `assistant-ui` 负责 thread/composer/message 运行时
- `project_id` 在前端 submit 时，通过 `configurable.project_id` 传给 graph
- assistant message 里的 citation metadata 会映射成底部 source chip

### 12.7 文档区 AI 入口

文档区当前仍然保留“两者都保留”的方案：

1. 固定右侧 AI 侧栏
2. 收起后保留一个悬浮入口按钮

另外，`SOLO Mode` 和 `Library Mode` 现在有了顶层显式切换按钮。

### 12.8 旧 SSE 接口的角色

`POST /agent/answer/stream` 没有删除。

它现在的角色是：
- 兼容旧前端调用
- 做快速调试
- 在不启动 LangGraph Agent Server 的情况下，仍能验证 retrieval + generation 主链

---

## 13. 当前系统的边界

### 已经打通的部分

- 扫描
- 解析
- 分块
- MySQL
- Qdrant
- 前端入库工作流
- Retrieval 第一版主链
- EvidencePack 真实构建
- LangGraph 单 Agent 问答主链
- 官方 `useStream` + `assistant-ui` 前端聊天运行时
- 文档区 AI 侧栏和 SOLO 聊天模式切换

### 还没打通的部分

- 记忆系统
- Planner / Critic / Memory 多节点图
- Hybrid retrieval
- 真正的图像 embedding 检索
- Web retrieval 汇总
- 更强的 citation 到 PDF / 图表跳转

---

## 14. 下一阶段应该做什么

下一阶段最合理的是：

1. 把 citations 做成可点击跳转 PDF / 图表
2. 在 LangGraph graph 上拆出 Planner / Retrieval / Writer
3. 再把 memory 接进主链
4. 最后再补 web search / hybrid retrieval

对应设计文档：

- `docs/retrieval-plan.md`

---

## 15. 一句话总结

当前 StudyAgent 已经不是“项目骨架”了，而是一个：

**能把 PDF 论文解析、入库、检索，并通过 LangGraph + 官方前端流式返回 grounded answer 的科研论文工作台。**

下一步不该再继续堆底层解析，而该进入：

**多节点 Agent 编排、citation 跳转和记忆增强。**
