# Retrieval Plan

## 目标

下一阶段实现三层检索：

1. 文档级 retrieval
2. 正文 chunk 级 retrieval
3. 视觉资产 asset 级 retrieval

目标不是立刻做 Agent，而是先把 Evidence Retrieval 底座打通。

## 为什么要做三层

当前系统已经有三类索引对象：

- `DocumentProfile`
  - 代表整篇论文的检索画像
- `Chunk`
  - 代表正文证据块
- `DocumentAsset`
  - 代表图、表、流程图等视觉资产

如果只检索正文 chunk，会有两个问题：
- 用户从整个文档库提问时，很难先稳定定位相关论文
- 图表证据会被忽略

所以更合理的流程是：

1. 先找相关论文
2. 再在候选论文里找正文
3. 再在候选论文里找图表

## 目标数据流

```text
User Query
  -> Document Retrieval
  -> Candidate Document IDs
  -> Chunk Retrieval
  -> Asset Retrieval
  -> Evidence Pack
```

## 当前基础

已经具备：

- MySQL
  - `documents`
  - `document_assets`
  - `chunks`
- Qdrant
  - `study_agent_documents`
  - `study_agent_chunks`
  - `study_agent_assets`
- Embedding provider
- `DocumentProfile`
- `IngestDocumentUseCase`

所以 Retrieval 阶段重点不是补底层解析，而是：
- 组织检索流程
- 统一返回结构
- 做候选集收缩和证据组装

## 推荐实现顺序

### Phase 1: 文档级检索

目标：
- 给一个 query，先返回候选论文列表

建议实现：
- `retrieve_documents(query, project_id, limit)`

输入：
- query
- project_id
- limit

输出：
- `list[Document]` 或文档级命中结构

检索来源：
- Qdrant `study_agent_documents`

查询向量建议：
- 先用 query 同时查：
  - `title`
  - `summary`

### Phase 2: chunk 检索

目标：
- 在候选论文里找正文证据

建议实现：
- `retrieve_chunks(query, project_id, document_ids, limit)`

输入：
- query
- project_id
- document_ids
- limit

输出：
- `list[Chunk]`

检索来源：
- Qdrant `study_agent_chunks`
- MySQL `chunks`

建议：
- 先在 Qdrant 拿 `chunk_id`
- 再回 MySQL 取完整 chunk 文本

### Phase 3: asset 检索

目标：
- 在候选论文里找图表证据

建议实现：
- `retrieve_assets(query, project_id, document_ids, limit)`

输入：
- query
- project_id
- document_ids
- limit

输出：
- `list[DocumentAsset]`

检索来源：
- Qdrant `study_agent_assets`
- MySQL `document_assets`

### Phase 4: Evidence Pack

目标：
- 把文档、正文、资产证据组合成统一结构

建议实现：
- `build_evidence_pack(query, document_hits, chunk_hits, asset_hits)`

输出建议：
- 候选文档摘要
- 正文 chunk 证据
- 图表证据
- 引用页码 / 文档 id

## 推荐代码放置

建议新建：

- `packages/rag/src/study_agent_rag/retrieval.py`
- `packages/rag/src/study_agent_rag/evidence.py`

或者如果你想先轻量落地，也可以先放：

- `packages/application/src/study_agent_application/retrieve_evidence_use_case.py`

## 建议的数据结构

### 文档命中

建议结构：
- `document_id`
- `title`
- `score`

### chunk 命中

建议结构：
- `chunk_id`
- `document_id`
- `page`
- `score`
- `text`

### asset 命中

建议结构：
- `asset_id`
- `document_id`
- `page_number`
- `asset_label`
- `caption`
- `summary`
- `score`

### EvidencePack

建议最终至少包含：
- `query`
- `documents`
- `text_chunks`
- `assets`

## 实现注意事项

### 1. 先做分层，不要一开始全局混搜

推荐流程：
- 先 `documents`
- 再 `chunks + assets`

### 2. 先做 dense retrieval，后续再补 sparse

当前先用现有 embedding + Qdrant 跑通。

后续可补：
- BM25
- 标题关键词召回
- hybrid retrieval

### 3. asset 检索先用 caption / summary

当前不做真正多模态图像检索，先用文本化视觉资产即可。

### 4. 先保证结果可解释

每条命中最好都能回到：
- `document_id`
- `page`
- `chunk_id / asset_id`

## 下一阶段完成标准

满足以下条件即可认为 Retrieval 阶段第一版完成：

- 可以从 query 先检索相关论文
- 可以在候选论文内检索正文 chunk
- 可以在候选论文内检索视觉资产
- 可以返回统一 `EvidencePack`
- 后续 Agent 可以直接消费这个结构
