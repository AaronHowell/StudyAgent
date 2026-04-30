# Phase 1 Prompt：整理 PaperLab 目录结构，为多模态问答和论文复现预留边界

你现在在本地 `StudyAgent` 工作区中工作。请先完成 **第一阶段：目录结构调整与代码边界整理**。

这一阶段的目标不是实现新功能，而是把现有 PaperLab 后端整理成更清晰、可扩展、可阅读的结构，为后续两个阶段做准备：

1. 阶段二：图片 + 文字的双模态论文证据回答。
2. 阶段三：基于 PLAN mode + Worker/Mailbox 的长期论文复现功能。

请保持实现简单直接，不要过度抽象。这个项目是学习项目，代码可读性优先。

---

## 一、阶段目标

完成后项目应该具备清晰边界：

```text
PaperLab/Server/
  api/
    main.py
    dependencies.py
    routes/
      health.py
      documents.py
      ingestion.py
      retrieval.py
      assets.py
      chat.py
      runs.py          # 先预留，可为空或轻量实现
    schemas/

  src/
    domain/
      __init__.py
      documents.py
      evidence.py
      memory.py
      tasks.py
      ports.py

    documents/
      scanner.py
      pdf_parser.py
      chunking.py
      assets.py

    indexing/
      document_indexer.py
      chunk_indexer.py
      asset_indexer.py

    retrieval/
      retriever.py
      fusion.py
      rerank.py
      evidence_pack.py

    generation/
      answer_writer.py
      message_builders.py
      citation_formatter.py
      prompts/
        grounded_answer.md
        multimodal_answer.md
        synthesis.md

    orchestration/
      supervisor.py
      graph_state.py
      graph_messages.py
      runtime_access.py
      request_config.py
      nodes/
        prepare_turn.py
        context.py
        route.py
        dispatch.py
        assess.py
        synthesize.py
        guidance.py

    workers/
      retriever/
        agent.py
      tool/
        agent.py
      workspace/
        agent.py
      reproduce/
        __init__.py
        README.md       # 先说明未来设计，不实现复杂逻辑

    workspace/
      __init__.py
      command_policy.py # 先预留，阶段三实现
      artifacts.py      # 先预留，阶段三实现

    integrations/
      llm/
      vectorstore/
      storage/
      sandbox/
      mcp/
      web/

    runtime/
      settings.py
      dependencies.py
      service_container.py

    memory/
      models.py
      service.py
      policy.py

    session_storage/

  tests/
    unit/
    integration/
    e2e/
```

如果当前项目已有部分目录，请基于现有结构渐进调整，不要为了“目录好看”大规模搬迁所有代码。

---

## 二、重要原则

1. **不要重写业务逻辑。**
2. **不要引入新框架。**
3. **不要破坏现有 API。**
4. **不要一次性实现论文复现。**
5. **不要为了架构创建大量空类。**
6. **允许添加少量空目录、README 或占位模块，但要说明用途。**
7. **保持旧 import 尽量兼容。**
8. **每次移动代码后修复 import 和测试。**

当前阶段只做结构整理和边界收敛。

---

## 三、必须先阅读的文件

开始前请阅读：

```text
PaperLab/Server/api/main.py
PaperLab/Server/src/domain/models.py
PaperLab/Server/src/domain/ports.py
PaperLab/Server/src/usecases/ingest_document.py
PaperLab/Server/src/usecases/retrieve_evidence.py
PaperLab/Server/src/usecases/answer_question.py
PaperLab/Server/src/prompts/builders.py
PaperLab/Server/src/documents/pdf_parser.py
PaperLab/Server/src/documents/chunking.py
PaperLab/Server/src/integrations/vectorstore/qdrant_store.py
PaperLab/Server/src/orchestration/supervisor.py
PaperLab/Server/src/orchestration/graph_state.py
PaperLab/Server/src/workers/retriever/agent.py
PaperLab/Server/src/workers/tool/agent.py
PaperLab/Server/src/workers/workspace/agent.py
PaperLab/Server/src/runtime/dependencies.py
PaperLab/Server/tests/test_layout.py
```

---

## 四、任务 1：瘦身 `api/main.py`

当前 `api/main.py` 过大。请拆成：

```text
api/main.py
api/dependencies.py
api/routes/health.py
api/routes/documents.py
api/routes/ingestion.py
api/routes/retrieval.py
api/routes/assets.py
api/routes/chat.py
api/routes/runs.py
```

### `api/main.py` 只保留

- 创建 FastAPI app
- 配置 CORS / middleware
- include routers
- lifespan
- uvicorn 启动入口

### `api/dependencies.py` 放

- `ApiServices`
- `get_services()`
- 现有服务初始化逻辑

### routes 拆分建议

- `health.py`
  - `/healthz`

- `documents.py`
  - `/documents/scan`
  - `/documents/images`
  - `/documents/file`
  - `/documents/ingestion-status`

- `ingestion.py`
  - `/documents/ingest`
  - `/documents/ingest/{task_id}`
  - `/documents/ingest/batch`
  - list ingestion tasks

- `retrieval.py`
  - `/retrieval/evidence`

- `assets.py`
  - `/documents/assets/{asset_id}/content`

- `chat.py`
  - `/agent/answer/stream`
  - 现有 chat/session router 如果已经存在，保持兼容

- `runs.py`
  - 先预留论文复现 run API 的 router
  - 可以只提供 placeholder 或不 include endpoint
  - 不要在第一阶段实现复杂逻辑

### 要求

- 现有 endpoint 路径不变。
- Response schema 不变。
- 前端不需要改。
- route 函数尽量短。
- 业务逻辑不要继续堆在 route 里。
- `api/main.py` 目标控制在 100 行左右。

---

## 五、任务 2：拆分 `domain/models.py`

当前 `domain/models.py` 越来越大。请拆为：

```text
src/domain/documents.py
src/domain/evidence.py
src/domain/memory.py
src/domain/tasks.py
src/domain/ports.py
src/domain/__init__.py
```

### 建议归属

`documents.py`：

```text
Project
Document
DocumentType
DocumentStatus
PdfPage
DocumentAsset
DocumentProfile
DocumentDiscoveryResult
ScanSummary
```

`evidence.py`：

```text
Chunk
ChunkType
Citation
ScoredId
DocumentHit
ChunkHit
AssetHit
EvidencePack
```

`memory.py`：

```text
MemoryType
MemoryItem
```

`tasks.py`：

```text
TaskCard
AgentTask
AgentResult
AgentArtifact
```

如果 `AgentTask / AgentResult / AgentArtifact` 当前在 `contracts`，可以暂时不迁移，只在 `tasks.py` 预留注释，避免过度搬迁。

### 兼容要求

`domain/__init__.py` 必须 re-export 旧对象，确保旧代码仍能：

```python
from domain import DocumentAsset, EvidencePack, Chunk
```

### 不要做

- 不要引入 ORM。
- 不要引入 Pydantic。
- 不要让 domain 依赖 FastAPI、Qdrant、MySQL、Redis、LangGraph。
- 不要做复杂继承层级。

---

## 六、任务 3：新增 `indexing` 边界

当前 `IngestDocumentUseCase` 里混合了解析、分块、存储、向量索引。第一阶段不要求完全重构，但请建立清晰边界：

```text
src/indexing/document_indexer.py
src/indexing/chunk_indexer.py
src/indexing/asset_indexer.py
```

建议实现轻量函数或类：

```python
class DocumentIndexer:
    def build_profile(...)
    def index_profile(...)

class ChunkIndexer:
    def index_chunks(...)

class AssetIndexer:
    def index_assets(...)
```

### 要求

- 可以先从 `IngestDocumentUseCase` 中抽出部分索引代码。
- 不要求重写全部 ingestion pipeline。
- 目标是让后续阶段二能自然加上 `image vector`。
- 保持现有 ingestion 行为不变。

---

## 七、任务 4：新增 `retrieval` 边界

当前 `RetrieveEvidenceUseCase` 文件过大，里面包含 retrieve、fusion、rerank、evidence pack 构造、debug log 等逻辑。

请逐步拆出：

```text
src/retrieval/retriever.py
src/retrieval/fusion.py
src/retrieval/rerank.py
src/retrieval/evidence_pack.py
```

### 建议

`retriever.py`：

- 放 `RetrieveEvidenceUseCase` 主流程，或保留 wrapper。
- 主流程应该读起来像 pipeline：

```text
embed query
retrieve documents
retrieve chunks
retrieve assets
rerank/fuse
build evidence pack
write debug log
```

`fusion.py`：

- `_fuse_document_hits`
- 后续阶段二需要 `fuse_asset_hits(summary, caption, image)`

`rerank.py`：

- document rerank
- chunk rerank
- asset rerank

`evidence_pack.py`：

- `build_evidence_pack`
- citation 构造

### 兼容要求

旧 import 路径如果有：

```python
from usecases import RetrieveEvidenceUseCase
```

必须仍然可用。可以在 `usecases/retrieve_evidence.py` 中 re-export 新实现。

---

## 八、任务 5：新增 `generation` 边界

当前 `prompts/builders.py` 负责太多 prompt。

请新增：

```text
src/generation/
  answer_writer.py
  message_builders.py
  citation_formatter.py
  prompts/
    grounded_answer.md
    multimodal_answer.md
    synthesis.md
```

第一阶段不要求重写回答逻辑，但请：

1. 将 `build_grounded_answer_prompt` 的新版本放入 `generation/message_builders.py`。
2. 保留 `prompts/builders.py` 作为兼容 wrapper。
3. prompt 文本尽量放到 `.md` 文件中。
4. 为阶段二预留：

```python
def build_multimodal_answer_messages(...):
    ...
```

可以先不完全实现，只返回 text-only fallback，但接口要清晰。

---

## 九、任务 6：轻量拆分 `orchestration/supervisor.py`

`supervisor.py` 很长。请不要一次性大改 graph 行为，但可以先拆节点文件：

```text
src/orchestration/nodes/
  prepare_turn.py
  context.py
  route.py
  dispatch.py
  assess.py
  synthesize.py
  guidance.py
```

### 要求

- `supervisor.py` 最终主要负责 graph wiring。
- 不改变 `PaperLabGraphState`。
- 不改变 LangGraph 行为。
- 如果一次性拆风险太大，可以只先移动最独立的 helper/node，并留下 TODO。
- 优先保证测试通过。

---

## 十、任务 7：预留论文复现目录

新增：

```text
src/workers/reproduce/
  __init__.py
  README.md
```

`README.md` 里说明未来阶段三设计：

```text
Reproduction Mode:
- PlanAgent
- fixed WorkerAgents
- per-agent mailbox
- task DAG
- sandbox command execution
- command policy + optional LLM safety classifier
```

新增：

```text
src/workspace/
  __init__.py
  command_policy.py
  artifacts.py
```

第一阶段可以只放轻量占位和文档，不实现复杂逻辑。

---

## 十一、测试要求

新增或更新测试：

```text
tests/unit/test_domain_exports.py
tests/unit/test_api_routes_import.py
tests/unit/test_generation_builders.py
tests/unit/test_retrieval_fusion.py
tests/test_layout.py
```

测试目标：

1. 旧 domain import 仍可用。
2. 新 routes 都能 import。
3. `api/main.py` 存在。
4. `generation/message_builders.py` 可 import。
5. `retrieval/fusion.py` 可 import。
6. `workers/reproduce/README.md` 存在。
7. `workspace/command_policy.py` 存在。

---

## 十二、阶段完成标准

第一阶段完成后：

- 现有功能不破坏。
- API 路径不变。
- `api/main.py` 明显变薄。
- `domain/models.py` 被拆分，旧 import 兼容。
- `retrieval / generation / indexing` 边界出现。
- `workers/reproduce` 和 `workspace` 目录为第三阶段预留。
- 测试通过。

不要实现多模态图片回答。
不要实现论文复现。
这两个留给第二、第三阶段。
