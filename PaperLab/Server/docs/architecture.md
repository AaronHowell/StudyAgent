# PaperLab Architecture

- `api`
  FastAPI 入口与 API 层任务装配。
- `src/orchestration`
  LangGraph supervisor 主循环与并行 worker 派发。
- `src/workers`
  `retriever` / `tool` / `workspace` 三个 worker。
- `src/memory`
  长期记忆读写与短期上下文压缩。
- `src/documents`
  文档扫描、PDF 解析、chunking。
- `src/usecases`
  入库、检索、问答用例。
- `src/integrations`
  MySQL、Qdrant、Mem0、Web/MCP、LLM 等外部接入。
