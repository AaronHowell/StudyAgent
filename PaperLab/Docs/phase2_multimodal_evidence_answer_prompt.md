# Phase 2 Prompt：实现图片 + 文字的双模态论文证据回答

你现在在本地 `StudyAgent` 工作区中工作。请在第一阶段目录结构整理完成的基础上，实现 **第二阶段：图片 + 文字的双模态论文证据回答**。

目标：当用户基于论文提问时，系统不仅能召回正文 chunk，还能召回论文中的图片/图表资产，并在回答时让 vision-capable LLM 真正看到图片，而不是只看到 caption 文本。

请保持实现简单直接，优先跑通主链路，不要引入复杂框架。

---

## 一、阶段目标

完成后应该支持：

1. PDF ingestion 阶段提取图片/图表资产。
2. asset 不仅有 caption/summary 文本向量，还支持 image vector。
3. retrieval 阶段可以同时召回：
   - document evidence
   - text chunk evidence
   - visual asset evidence
4. answer 阶段可以构造多模态消息：
   - text evidence 作为文本块
   - top visual assets 作为 image blocks
5. 回答中支持：
   - 文本引用 `[C1]`
   - 图片引用 `[A1]`
6. 没有 vision model 或没有图片时，自动 fallback 到 text-only 回答。

---

## 二、先阅读这些文件

```text
PaperLab/Server/src/domain/ports.py
PaperLab/Server/src/domain/evidence.py
PaperLab/Server/src/domain/documents.py
PaperLab/Server/src/documents/pdf_parser.py
PaperLab/Server/src/indexing/asset_indexer.py
PaperLab/Server/src/retrieval/retriever.py
PaperLab/Server/src/retrieval/fusion.py
PaperLab/Server/src/retrieval/evidence_pack.py
PaperLab/Server/src/generation/message_builders.py
PaperLab/Server/src/generation/answer_writer.py
PaperLab/Server/src/generation/citation_formatter.py
PaperLab/Server/src/integrations/vectorstore/qdrant_store.py
PaperLab/Server/src/usecases/answer_question.py
PaperLab/Server/src/usecases/retrieve_evidence.py
PaperLab/Server/api/routes/retrieval.py
PaperLab/Server/api/routes/assets.py
```

如果第一阶段没有完全拆分，基于现有结构完成同等功能，但要尽量放到上述边界中。

---

## 三、核心设计

多模态 RAG 链路：

```text
PDF
  -> text pages
  -> text chunks
  -> visual assets
  -> document index
  -> chunk index
  -> asset caption/summary/image index
  -> retrieve documents
  -> retrieve chunks
  -> retrieve assets
  -> build EvidencePack
  -> load top asset image bytes
  -> build multimodal LLM messages
  -> stream grounded answer
```

---

## 四、任务 1：扩展 EmbeddingProvider 支持 image embedding

在 `domain/ports.py` 中确认或补充：

```python
class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_images(self, image_paths: list[str]) -> list[list[float]]:
        ...
```

要求：

- 如果已有 `embed_images`，保持兼容。
- 如果某些 provider 暂不支持 image embedding，可以默认抛出 `NotImplementedError`。
- 调用方必须能优雅降级，不要因为 image embedding 不支持导致整篇论文 ingestion 失败。

---

## 五、任务 2：Qdrant asset collection 增加 image named vector

修改 `integrations/vectorstore/qdrant_store.py`。

新增常量：

```python
ASSET_VECTOR_CAPTION = "caption"
ASSET_VECTOR_SUMMARY = "summary"
ASSET_VECTOR_IMAGE = "image"
```

修改：

```python
ensure_asset_collection(
    caption_vector_size: int,
    summary_vector_size: int,
    image_vector_size: int | None = None,
)
```

如果 `image_vector_size` 不为空，则 collection 包含 image named vector。

修改：

```python
upsert_assets(
    assets: list[DocumentAsset],
    caption_vectors: list[list[float]],
    summary_vectors: list[list[float]],
    image_vectors: list[list[float]] | None = None,
)
```

要求：

- image_vectors 可选。
- 没有 image_vectors 时保持旧行为。
- collection 已存在但缺少 image vector 时，开发阶段可以重建 collection，但要记录日志或注释说明。
- search_assets 支持 `vector_name="image"`。

---

## 六、任务 3：AssetIndexer 写入 caption / summary / image 三类向量

在 `indexing/asset_indexer.py` 中实现或完善：

```python
class AssetIndexer:
    def index_assets(self, assets: list[DocumentAsset]) -> None:
        ...
```

逻辑：

1. 构造 caption texts：
   - `asset.caption`
   - fallback 到 `asset.asset_label`
   - fallback 到 `asset.file_name`

2. 构造 summary texts：
   - `asset.summary`
   - fallback 到 caption
   - fallback 到 asset_type

3. 尝试构造 image paths：
   - 优先使用 `asset.file_path`
   - 如果 asset 有 `content_bytes` 但没有 file_path，可以写入 cache 文件再 embedding
   - 如果无法构造 image path，则跳过 image vector

4. 调用：
   - `embedding_provider.embed_texts(caption_texts)`
   - `embedding_provider.embed_texts(summary_texts)`
   - 尝试 `embedding_provider.embed_images(image_paths)`

5. 调用 vector store：
   - `upsert_assets(..., caption_vectors, summary_vectors, image_vectors=image_vectors_or_none)`

要求：

- 任意单张图片 embedding 失败，不要导致整篇论文 ingestion 失败。
- 可以记录 warning。
- 如果 image embedding 整体不可用，则仍然写 caption/summary vectors。
- 保持现有 ingestion 行为兼容。

---

## 七、任务 4：asset 检索改为多路融合

在 `retrieval/retriever.py` 和 `retrieval/fusion.py` 中实现 asset 多路召回。

当前可能只搜：

```text
asset summary vector
```

请改成可配置的多路检索：

```text
asset summary vector
asset caption vector
asset image vector
```

实现：

```python
def fuse_asset_hits(
    summary_hits: list[ScoredId],
    caption_hits: list[ScoredId],
    image_hits: list[ScoredId],
    limit: int,
) -> list[ScoredId]:
    ...
```

建议初始权重：

```text
summary: 1.0
caption: 0.9
image: 1.1
rank bonus: 1 / (rank + 1)
```

要求：

- 如果 image vector 不可用，自动跳过 image_hits。
- 如果 caption vector 不可用，自动跳过 caption_hits。
- 去重按 asset_id。
- 保留现有 rerank 逻辑。
- debug log 中记录 raw asset hits 来源：
  - summary
  - caption
  - image
  - fused
  - reranked

---

## 八、任务 5：EvidencePack 支持 asset citation

在 `domain/evidence.py` 或 `retrieval/evidence_pack.py` 中补充图片引用能力。

建议新增：

```python
@dataclass(slots=True)
class AssetCitation:
    asset_id: str
    document_id: str
    document_title: str
    page: int | None
    label: str
    locator: str
```

或者复用 `Citation`，但要能区分 text citation 和 asset citation。

`EvidencePack` 建议包含：

```python
text_chunks: list[ChunkHit]
assets: list[AssetHit]
citations: list[Citation]
asset_citations: list[AssetCitation]
```

要求：

- 文本证据引用格式 `[C1]`
- 图片证据引用格式 `[A1]`
- 回答 done event 中返回两类 citations
- API retrieval response 中尽量保持向后兼容，可以新增字段但不要删除旧字段

---

## 九、任务 6：加载图片内容用于多模态回答

新增或完善：

```text
generation/multimodal_context.py
```

定义：

```python
@dataclass(slots=True)
class TextEvidenceItem:
    ref_id: str  # C1
    chunk_id: str
    document_id: str
    page: int | None
    text: str

@dataclass(slots=True)
class ImageEvidenceItem:
    ref_id: str  # A1
    asset_id: str
    document_id: str
    page: int | None
    caption: str
    summary: str
    media_type: str
    image_bytes: bytes | None
    image_path: str | None

@dataclass(slots=True)
class MultimodalEvidenceContext:
    question: str
    text_items: list[TextEvidenceItem]
    image_items: list[ImageEvidenceItem]
```

实现函数：

```python
build_multimodal_context(
    question: str,
    evidence_pack: EvidencePack,
    asset_repository: DocumentAssetRepository,
    max_images: int = 4,
) -> MultimodalEvidenceContext
```

要求：

- 只加载 top `max_images` 张图片。
- 图片太大时 resize 或跳过。
- 图片不可读时 fallback 到 caption/summary。
- 不要把 image bytes 存进 EvidencePack。
- image bytes 只在 generation 阶段短暂使用。

---

## 十、任务 7：构造多模态 LLM messages

在 `generation/message_builders.py` 中实现：

```python
build_multimodal_answer_messages(context: MultimodalEvidenceContext) -> list[dict]
```

消息结构应支持 OpenAI-compatible vision API 或项目当前 LLMProvider 能接受的格式。

建议内容：

System：

```text
You are PaperLab. Answer only from the provided paper evidence.
Use [C1], [C2] for text evidence.
Use [A1], [A2] for image evidence.
If evidence is insufficient, say so clearly.
Do not invent facts.
```

User content 中包含：

1. 文本问题
2. text evidence XML-like block
3. image evidence metadata XML-like block
4. image blocks

文本边界示例：

```xml
<question>
...
</question>

<text_evidence>
<chunk ref="C1" document_id="..." page="3">
...
</chunk>
</text_evidence>

<image_evidence>
<image ref="A1" asset_id="..." document_id="..." page="5">
caption: ...
summary: ...
The actual image is attached as image block A1.
</image>
</image_evidence>
```

要求：

- 不要把 base64 图片塞到普通 text prompt。
- 图片应该作为 image block 传给 LLM。
- 如果当前 LLMProvider 不支持 image block，则 fallback 到 text-only prompt。

---

## 十一、任务 8：扩展 LLMProvider 支持多模态

在 `domain/ports.py` 或 integrations/llm 中新增兼容方法：

```python
class MultimodalLLMProvider(Protocol):
    def stream_multimodal(self, messages: list[dict]) -> Iterable[str]:
        ...
```

或者在现有 LLMProvider 中增加：

```python
def stream_generate_messages(self, messages: list[dict]) -> Iterable[str]:
    ...
```

要求：

- 不破坏现有 `stream_generate(prompt: str)`。
- `AnswerQuestionUseCase` 可以检测 provider 是否支持多模态。
- OpenAI-compatible provider 如果支持 vision，就实现 message-based streaming。
- 不支持则 fallback。

---

## 十二、任务 9：修改 AnswerQuestionUseCase / AnswerWriter

在 `generation/answer_writer.py` 或 `usecases/answer_question.py` 中：

流程改为：

```text
retrieve evidence
build multimodal context
if assets exist and llm supports multimodal:
    build multimodal messages
    stream_multimodal
else:
    build text prompt
    stream_generate
```

meta event 增加：

```json
{
  "multimodal": true,
  "image_count": 3,
  "text_evidence_count": 8,
  "asset_evidence_count": 4
}
```

done event 增加：

```json
{
  "citations": [...],
  "asset_citations": [...]
}
```

要求：

- 旧前端如果只读 `citations` 不会坏。
- 新前端可以读取 `asset_citations`。
- 异常时 fallback 到 text-only，而不是直接失败。

---

## 十三、任务 10：Prompt 文件

新增或更新：

```text
generation/prompts/multimodal_answer.md
```

内容要求：

```text
# Role
You are PaperLab, a paper-grounded research assistant.

# Rules
- Answer only from provided text and image evidence.
- Cite text evidence with [C1], [C2].
- Cite image evidence with [A1], [A2].
- If the image shows information not present in caption, mention that it comes from the figure.
- If the evidence is insufficient, say so.
- Do not invent metrics, model names, or conclusions.
```

---

## 十四、测试要求

新增测试：

```text
tests/unit/test_asset_fusion.py
tests/unit/test_multimodal_context.py
tests/unit/test_multimodal_message_builder.py
tests/unit/test_answer_writer_fallback.py
tests/unit/test_asset_citations.py
```

测试内容：

1. `fuse_asset_hits` 能融合 summary/caption/image。
2. 没有 image hits 时仍能工作。
3. multimodal context 只加载 top N 图片。
4. image 读取失败时 fallback 到 caption。
5. message builder 输出包含：
   - `<text_evidence>`
   - `<image_evidence>`
   - image block
6. 不支持 multimodal LLM 时 fallback 到 text-only。
7. done event 包含 asset citations。

---

## 十五、不要做的事

不要：

- 不要在第二阶段实现论文复现。
- 不要引入 PlanAgent / Worker / Mailbox。
- 不要重写整个 LangGraph supervisor。
- 不要把图片 bytes 存进 GraphState 或 EvidencePack。
- 不要把 base64 图片直接拼进普通 prompt。
- 不要因为 image embedding 不可用导致 ingestion/retrieval 崩溃。
- 不要要求所有 LLM 都支持 vision。
- 不要删除旧 text-only 回答能力。

---

## 十六、阶段完成标准

第二阶段完成后：

1. 文本 chunk 和图片 asset 都可以被召回。
2. asset 支持 caption/summary/image 多路向量召回；image 不可用时可降级。
3. EvidencePack 包含 text evidence 和 image evidence。
4. 回答时 vision-capable LLM 能接收 top images。
5. 回答支持 `[C1]` 和 `[A1]` 引用。
6. 不支持 vision 时 text-only fallback 正常。
7. 测试通过。
