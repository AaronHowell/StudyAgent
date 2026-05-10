# Supervisor、RetrieveAgent、Memory 的当前提示词说明

本文档说明当前 PaperLab 后端中 supervisor、RetrieveAgent、memory 相关模块实际使用的提示词。对应代码主要在：

- `Server/src/prompts/builders.py`
- `Server/src/orchestration/supervisor.py`
- `Server/src/workers/retriever/agent.py`
- `Server/src/integrations/storage/markdown_memory_store.py`

## 总览

当前系统里有一个主 supervisor 图，以及 retriever/tool 等 specialist 子图。Memory 目前不是一个独立 LangGraph 子图；它由 supervisor 在 `main_route_node` 中决定是否执行，并下发 `run_memory`、`memory_query`、`memory_reason`，然后 `recall_memory_node` 调用 `MemoryService.recall(...)`。

新加的投机执行不会改变正式提示词。它只是先用原始用户问题启动 memory recall 和 retrieval，正式 `memory_query` / `retrieve_task` 到达后再用 reranker、embedding 或 token overlap 判断能否复用。

## CacheHit 友好结构

当前提示词按“稳定前缀、动态后缀”的原则组织，以提高模型端 prefix cache / CacheHit 的命中概率：

1. 不变的角色、规则、schema、输出格式、工具约束放在 prompt 前半段。
2. 每轮变化的用户问题、短期上下文、memory 命中、specialist 结果、retrieval working context 放在后半段。
3. 动态段统一用 `Dynamic ... payload:` 标记，便于后续维护时避免把变量内容重新放回前缀。

因此，下文展示的 prompt 结构以当前 CacheHit 优化后的顺序为准。

## Supervisor 提示词

### 1. 主路由提示词：`main_route_node`

位置：

- `Server/src/orchestration/supervisor.py`
- `Server/src/prompts/builders.py::build_main_route_messages`

调用方式：

```python
SystemMessage(content=system_prompt)
HumanMessage(content=user_prompt)
```

System prompt：

```text
You are the coordinator for weak speculative multi-agent dispatch.
```

Human prompt 先放稳定规则：

```text
Decide whether to dispatch memory recall, retrieval, and/or external tool specialists.
```

核心路由规则：

```text
Use each capability according to what kind of information is missing.
- Memory recall is for prior user preferences, durable project facts, or earlier conversation conclusions.
- Dispatch retrieval when the missing information should be grounded in the local project corpus.
- Retrieval is for project-grounded information that should come from the local paper/document corpus, including document inventory, metadata, passages, figures, tables, and evidence-backed project state.
- Tool specialist is for web or MCP-backed external information that is not expected to live in the local project corpus.
- If local file tools are enabled later in the answer stage, use them directly instead of dispatching a workspace specialist.

Route by information source and required grounding, not by surface phrasing alone.
- If the user is asking what is currently known, what papers are available, what evidence has already been uploaded, or what the project corpus currently contains, retrieval is usually the correct source because the answer should be grounded in local documents even if the question sounds broad.
- If short-term context and memory are thin but the answer could be established from project documents, prefer retrieval over guessing or looping without specialists.
- If the answer can already be given from short-term context or memory, avoid unnecessary retrieval.
```

动态内容放在最后：

```text
Dynamic request payload:

Question:
{question}
```

如果存在短期上下文，会追加：

```text
Short-term context:
{short_term_context}
```

如果已经有 memory 上下文，会追加：

```text
Relevant memory:
{memory_context}
```

如果用户在循环中插入了新指导，会追加：

```text
New user guidance:
- {intervention}
```

如果上一轮 assessment 给了继续检索建议，会追加：

```text
Assessment guidance from previous evidence review:
- {assessment_guidance}
```

跨论文综合类问题的特殊规则：

```text
For broad synthesis, comparison, survey, or research-landscape questions over multiple local papers:
- Do not pass the user's high-level synthesis request to retrieval unchanged.
- First decide what evidence fields are needed from the papers, such as research problem, method/system, main findings, limitations, and scope.
- Then dispatch retrieval with a structured evidence-gathering task that asks for those fields, so the supervisor can do the final cross-paper synthesis itself.
- Prefer one batched retrieval task with explicit evidence needs over many per-paper micro-tasks unless the user explicitly asks for paper-by-paper deep dives.
```

retrieval 容量提示：

```text
Retrieval capacity notes:
- Each retrieval call returns up to 5 text chunks and 6 visual assets (figures, tables). This limit is per-retrieval, not per-turn.
- If the first retrieval does not cover enough ground, you can dispatch another retrieval task with a different query to gather additional evidence in the same turn.
- Visual assets (figures, tables, diagrams) are retrieved alongside text chunks. When the question references figures, tables, or visual content, make sure to dispatch a retrieval task.
```

该提示词绑定 `_dispatch_schema()` 工具。模型输出会被解析成：

- `run_memory`
- `memory_query`
- `memory_reason`
- `run_retrieval`
- `retrieval_query`
- `retrieval_reason`
- `run_tool`
- `tool_query`
- `tool_reason`

### 2. Answer-or-loop 提示词：`assess_node`

位置：

- `Server/src/orchestration/supervisor.py::assess_node`
- `Server/src/prompts/builders.py::build_answer_or_continue_prompt`

用途：判断现有 memory、retrieval、tool 结果是否足够回答；如果不足，要求继续 evidence loop。

稳定规则先出现：

```text
Decide whether the available specialist evidence is enough to answer the user's question.
```

核心输出规则：

```text
If evidence is enough, return valid JSON with exactly four top-level keys: `answer_confident`, `answer`, `summary`, and `next_tasks`; set `answer_confident` to true, put the user-facing grounded reply in `answer`, put an object with string fields `done`, `next`, and `pending` in `summary`, and set `next_tasks` to an empty list.

If evidence is insufficient and the loop can continue, do not answer; call the virtual `continue_evidence_loop` tool with a reason and concrete follow-up evidence tasks. Choose follow-up evidence tasks by the missing information source.
- Ask for retrieval when the missing answer should come from the local project corpus, including broad project-state questions that need document-backed grounding.
- Ask for memory recall only when the missing answer depends on prior conversation facts or durable user/project preferences.
- Ask for external tool use only when the missing answer is not expected to be in local documents.
```

动态 payload 放在最后：

```text
Dynamic answer-or-loop payload:

Question:
{question}
```

随后按需拼接：

```text
Short-term context:
{short_term_context}

Relevant memory:
{memory_context}

New user guidance:
- {intervention}

Specialist results:
{retrieve_result}

{tool_result}
```

如果已经达到循环停止条件，会追加：

```text
The loop has reached its stop condition. Provide the best grounded answer possible, clearly naming any missing or uncertain evidence.
```

它还强调：

```text
For inventory/basic-info questions such as listing uploaded papers or document titles, document-level metadata is sufficient evidence; do not require chunk quotations or asset retrieval.

For corpus-level thematic overviews, a document-level synthesis grounded in titles and summaries can also be sufficient when the user did not ask for passage-level proof.

When the available specialist results already provide a coherent, grounded overview that directly addresses the user's scope, prefer answering now instead of requesting more evidence.

Do not chase perfect completeness by default.
```

`assess_node` 会再追加 memory write policy，并绑定：

- `continue_evidence_loop`
- `decide_memory_write`

### 3. 最终综合提示词：`synthesize_node`

位置：

- `Server/src/orchestration/supervisor.py::synthesize_node`
- `Server/src/prompts/builders.py::build_synthesis_prompt`

用途：根据已有上下文、memory、specialist 结果生成最终回答。

稳定输出规则先出现：

```text
Return valid JSON with exactly two top-level keys: `answer` and `summary`.
`answer` is the user-facing grounded reply.
`summary` must be an object with string fields `done`, `next`, and `pending`.
`done` should briefly state what this step completed.
`next` should state the most useful next follow-up.
`pending` should state what is still missing, uncertain, or not yet done.
Do not include chain-of-thought or extra keys.
```

动态输入放在最后：

```text
Dynamic synthesis payload:

Question:
{question}

Short-term context:
{short_term_context}

Relevant memory:
{memory_context}

New user guidance:
- {intervention}

Specialist results:
{retrieve_result}

{tool_result}
```

回答策略：

```text
Default to a useful, appropriately scoped answer based on the available grounded evidence.
Do not over-investigate or expand the scope on your own just because deeper detail might exist.
If the current evidence is enough for a solid overview, answer now and let the user decide whether to go deeper in a follow-up.
```

图片引用规则：

```text
When referencing figures, tables, or diagrams from the retrieved assets, use inline tags like <ref pic>A1</ref pic>, <ref pic>A2</ref pic>, etc. where the ref_id matches the asset's ref_id from the retrieval results.
```

### 4. 长期记忆写入策略：`decide_memory_write`

位置：

- `Server/src/orchestration/supervisor.py::_append_memory_write_policy`
- `Server/src/orchestration/supervisor.py::_memory_write_tool_schema`

工具说明：

```text
Decide whether to write a cross-session long-term memory from this completed turn. This memory is durable across future sessions, so default to no write unless the content is clearly stable and reusable.
```

工具参数：

- `action`: `none` 或 `store`
- `memory_type`: `preference`、`project_fact`、`research_episode`
- `content`
- `reason`

追加到最终回答提示词后的 policy：

```text
Memory write policy:
- You must call `decide_memory_write` exactly once after producing the final answer.
- This memory is long-term and cross-session, not short-term scratch space.
- Default to `action=none`.
- Use `action=store` only for stable long-term user preferences, durable project facts, shared project constraints, or reusable research lessons.
- Stable name/preferred form of address, enduring collaboration preferences, and declared long-term research directions are valid long-term memory candidates.
- Do not store ordinary answers, temporary tasks, uncertain claims, private/sensitive data, or details that can simply be re-retrieved from papers later.
- If you say in the answer that you will remember, have remembered, or will use this preference later, the tool call must be `action=store` with the exact durable fact to persist.
- If not storing, do not claim that the information has been remembered across sessions.
- If unsure, call `decide_memory_write` with `action=none`.
```

## RetrieveAgent 提示词

RetrieveAgent 有两层模型调用：先做 retrieval intent planning，再绑定 retrieval tools 执行检索。

### 1. 检索意图规划提示词

位置：

- `Server/src/workers/retriever/agent.py::_build_retrieval_planning_messages`

System prompt：

```text
You are RetrievalAgent. Before calling any retrieval tools, decide the retrieval intent and the lowest database level needed to answer the task.

{retrieval_schema_summary}

Return valid JSON with exactly these keys: `intent`, `target_level`, `need_semantic_search`, `need_chunk_fetch`, `need_asset_search`, `max_steps`, `rationale`.
- `intent` must be one of `inventory`, `evidence`, `visual`, `mixed`.
- `target_level` must be one of `document`, `chunk`, `asset`.
- Use `document` for titles/counts/basic metadata.
- Use `chunk` for passages, methods, results, claims, page-level evidence.
- Use `asset` for figures, tables, diagrams, or visual content.
- Broad project-state questions such as what is currently known, what documents are available, or what local evidence exists should still be grounded in the local corpus; choose the lowest level that can answer them.
- Prefer the lowest sufficient retrieval level. Do not escalate from document to chunk or asset unless the user's question actually requires deeper evidence.
- Do not pursue maximal completeness on your own. If document-level synthesis is already enough for a solid answer, stop there and let the user ask for deeper analysis later.
- Choose a plan that can likely finish within a small number of steps. Do not plan open-ended exploration.
- If `target_level` is `document`, default to metadata lookup and avoid semantic search unless clearly needed.
- For corpus-wide overview across many papers, prefer batch tools such as `search_documents_qdrant`, `search_chunks_mysql`, or `fetch_documents_chunks_mysql` over one-document-at-a-time loops.
- Do not include markdown or any text outside the JSON object.
```

Human prompt：

```text
Dynamic retrieval task:

Task query:
{task.query}

Reason:
{task.reason}

Think about the task semantics, not just keywords, and choose the minimal retrieval level that can answer it.
```

`retrieval_schema_summary` 会说明当前数据库和索引：

- MySQL `documents`
- MySQL `chunks`
- MySQL `document_assets`
- Qdrant document vectors
- Qdrant chunk vectors
- Qdrant asset vectors

### 2. 检索执行提示词

位置：

- `Server/src/workers/retriever/agent.py::_run_retrieve_specialist_with_trace`
- `Server/src/workers/retriever/agent.py::_build_retrieval_execution_instruction`

System prompt：

```text
You are RetrievalAgent. Your job is to gather local evidence with retrieval tools and then finish with the strongest document/chunk/asset ids.

{retrieval_schema_summary}

Follow this plan strictly.
You have at most {retrieval_agent_max_steps} tool rounds in total.
Stop as soon as the current evidence is enough for the smallest accurate answer.
Do not expand scope on your own for speculative completeness.
If you reach the final round, you must finish with the best grounded summary you have and note any optional unfinished follow-up in `pending`.

Approved retrieval plan:
{intent_plan_json}
```

如果 plan 的 `target_level=document`，追加：

```text
Stay at the document level. Use `search_documents_mysql` with `keyword=""` for full project inventory or a literal metadata keyword when the task names a specific title/file. Do not fetch chunks or assets.
```

如果 `target_level=chunk`，追加：

```text
You may use document narrowing plus chunk retrieval. Prefer `fetch_documents_chunks_mysql` or scoped multi-document chunk search when the task asks for many-document summaries. Fetch exact chunks only when chunk-level evidence is required.
```

如果 `target_level=asset`，追加：

```text
You may use document narrowing plus asset retrieval. Do not fetch chunk text unless the visual task also requires textual support.
```

按 plan 还可能追加：

```text
Avoid Qdrant semantic search unless metadata lookup fails to satisfy the plan.
Do not call chunk-fetch tools.
Do not call asset-search tools.
```

Human prompt：

```text
Dynamic retrieval execution payload:

Task query:
{task.query}

Reason:
{task.reason}

Prior retrieval working context:
{recent_retrieval_working_context}

Plan the retrieval path yourself. You may use MySQL-only lookup, Qdrant-only lookup, or a multi-step flow such as document narrowing then chunk retrieval. When enough evidence has been gathered, call finish_retrieval.
```

### 3. RetrieveAgent 可调用工具

RetrieveAgent 绑定的工具包括：

- `search_documents_mysql`
- `search_documents_qdrant`
- `search_chunks_qdrant`
- `search_chunks_mysql`
- `fetch_document_chunks_mysql`
- `fetch_documents_chunks_mysql`
- `fetch_chunks_mysql`
- `search_assets_qdrant`
- `fetch_assets_mysql`
- `finish_retrieval`

最终必须通过 `finish_retrieval` 提交：

- `document_ids`
- `chunk_ids`
- `asset_ids`
- `summary`
- `completed`
- `pending`

### 4. 检索兜底总结提示词

位置：

- `Server/src/workers/retriever/agent.py::_synthesize_fallback_retrieval_conclusion`

当工具轮次结束但 summary 太弱时，会要求模型基于已有 evidence digest 写一个检索总结。

System prompt：

```text
You are closing a retrieval step. Based only on the provided local evidence, write a concise grounded retrieval conclusion that directly answers the retrieval task. Be useful enough with the evidence already in hand. Do not ask for more retrieval, do not emit JSON, and do not mention tool internals.
```

Human prompt：

```text
Retrieval task query:
{task.query}

Retrieval task reason:
{task.reason}

Intent plan:
{intent_plan_json}

Evidence digest:
{evidence_digest}

Write the retrieval conclusion in plain text.
```

## Memory 相关提示词

### 1. 当前没有独立 MemoryAgent 子图

当前代码中 memory recall 的正式路径是：

```text
main_route_node 由 supervisor LLM 决定:
- run_memory
- memory_query
- memory_reason

recall_memory_node 使用 memory_query 调用:
MemoryService.recall(role="supervisor", query=memory_query, project_id=..., limit=...)
```

因此，memory 的“任务”来自 supervisor，但没有像 RetrieveAgent 那样的 `build_memory_agent_graph`。

投机执行中会先构造一个内部 `AgentTask`：

```text
task_type = memory_recall
agent_name = memory_agent
query = 原始用户问题
reason = Speculative memory recall from raw user input.
constraints = {"limit": request_config.memory_limit}
```

正式 `memory_query` 下来后，再和投机 query 做语义匹配，命中则复用。

### 2. MemoryService recall 本身没有 LLM 提示词

位置：

- `Server/src/memory/service.py::MemoryService.recall`

`MemoryService.recall(...)` 本身只做：

1. 根据 role 读取 memory policy。
2. 如果长期记忆未开启或 backend 不存在，返回空。
3. 调用 backend 的 `search(query, project_id, limit)`。
4. 如果有 hits，组装：

```text
Relevant memory:
- {memory_item.content}
- {memory_item.content}
```

5. 如果没有 hits，调用 backend 的 `summarize_for_project(project_id)`。

所以真正有没有 LLM 提示词取决于 backend。

### 3. Markdown memory selector 提示词

位置：

- `Server/src/integrations/storage/markdown_memory_store.py::ChatModelMarkdownMemorySelector`

用于从 `memory.md` 中筛选与当前请求有关的长期记忆。

Prompt：

```text
You select long-term memory for the current answer.
Be conservative. Return only memory entries that are directly useful for this user request.
Return at most 5 bullets. If nothing is relevant, return exactly: Relevant memory:\n- none
Do not answer the user's request. Do not infer new facts. Do not include unrelated memory.

Dynamic memory selection payload:

User request:
{query}

Full memory.md:
{memory_markdown}
```

### 4. Markdown memory write manager 提示词

位置：

- `Server/src/integrations/storage/markdown_memory_store.py::ChatModelMarkdownMemoryWriteManager`

用于判断候选 memory 是否应该写入 `memory.md`。

Prompt：

```text
You manage a long-term cross-session memory file for a research assistant.
Read the full memory markdown and the proposed new memory entry, then decide whether to store it.
Be conservative.
Return valid JSON with exactly three keys: action, content, reason.
- action must be one of: store, skip, merge
- content must be the final normalized memory text to save when action is store or merge; otherwise use an empty string
- reason must briefly explain the decision
Skip if the candidate is already covered by existing memory, too temporary, too generic, or not useful across sessions.
Merge if the candidate should update/normalize an existing durable preference or fact.
Store if it is a new durable preference, project fact, or reusable research lesson.

Dynamic memory write payload:

Memory type:
{memory_type.value}

Write request context:
{query}

Candidate memory:
{candidate_content}

Full memory.md:
{memory_markdown or '(empty)'}
```

### 5. Mem0 backend

如果使用 `mem0` backend，具体内部提示词由 Mem0 库和其配置决定，不在当前仓库中直接定义。当前仓库只负责在 runtime 中配置 Mem0 的 LLM、embedder、vector store，并通过 `MemoryService` 调用其 search/store 能力。

## 三者之间的任务关系

### Supervisor

Supervisor 决定本轮是否需要：

- memory recall
- local retrieval
- external tool

它负责把用户问题改写成面向 specialist 的 query/reason，并在 evidence 足够后生成最终回答。

### RetrieveAgent

RetrieveAgent 只处理本地项目语料库检索。它先判断最低检索层级，再调用 MySQL/Qdrant 工具，最后通过 `finish_retrieval` 返回结构化证据。

### Memory

Memory 负责长期记忆读取和写入：

- 读取由 supervisor 的 `memory_query` 触发。
- 写入由最终回答阶段的 `decide_memory_write` 工具触发。
- 当前没有独立 MemoryAgent 子图，但投机执行里内部使用 `memory_agent` 作为任务名来统一追踪。
