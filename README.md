# StudyAgent

StudyAgent 是一个面向单用户科研场景的桌面论文助手学习项目。当前重点已经从“Step 1 骨架”进入到“文档入库与检索底座”阶段。

## 当前实现状态

已完成：
- React + Vite 桌面前端工作台
- FastAPI 后端
- PDF 扫描、标题提取、页文本解析
- 视觉资产提取与缓存
- 文本分块与近似 token 预算控制
- MySQL 持久化
- Qdrant 文档级 / chunk 级 / 视觉资产级索引
- 后台并发入库任务与前端任务面板

未完成：
- LangGraph 多 Agent 工作流
- 真正的聊天问答主链路
- Redis 记忆管理
- 真多模态图片 embedding
- OCR / 表格区域渲染增强

## 技术栈

- Desktop: React + Vite + TypeScript
- API: FastAPI
- Document Parsing: `pypdf` + `PyMuPDF`
- Storage: MySQL + Qdrant
- Embedding: OpenAI-compatible `/embeddings` API
- Orchestration: LangGraph（下一阶段接入）

## 项目结构

```text
StudyAgent/
├── apps/
│   ├── api/
│   └── desktop/
├── docs/
├── packages/
│   ├── application/
│   ├── documents/
│   ├── domain/
│   ├── integrations/
│   ├── agents/
│   ├── memory/
│   └── rag/
├── DATABASE_SCHEMA.md
└── README.md
```

## 配置

根目录 `.env` 统一维护：
- MySQL / Redis / Qdrant
- LLM / Embedding 服务
- 入库并发与超时

关键配置包括：
- `STUDY_AGENT_MYSQL_*`
- `STUDY_AGENT_QDRANT_*`
- `STUDY_AGENT_EMBEDDING_*`
- `STUDY_AGENT_INGEST_*`

## 启动方式

### 1. 安装依赖

```bash
uv sync --all-packages
cd apps/desktop
npm install
```

### 2. 启动 API

```bash
uv run --package study-agent-api uvicorn study_agent_api.main:app --reload
```

健康检查：

```text
http://127.0.0.1:8000/healthz
```

### 3. 启动前端

```bash
cd apps/desktop
npm run dev
```

## 当前主要 API

- `POST /documents/scan`
- `POST /documents/images`
- `POST /documents/ingestion-status`
- `POST /documents/ingest`
- `GET /documents/ingest/{task_id}`
- `GET /documents/ingest`
- `POST /documents/ingest/batch`
- `GET /documents/file`

详细说明见：
- `docs/api-reference.md`
- `docs/retrieval-plan.md`

## 当前验证结论

已完成一次函数级端到端验证，输入文件：

```text
C:\Users\Aaron_Howell\Desktop\postgraduate\PaperStore\STAC.pdf
```

验证链路：
- 扫描
- PDF 解析
- 分块
- 入库
- MySQL 检查
- Qdrant 检查
- 测试数据清理

验证结果摘要：
- 成功发现目标 PDF
- 成功解析 30 页
- 成功提取 5 个视觉资产
- 成功生成 79 个 chunk
- chunk 近似 token 最大值 420，没有超过预算
- 成功写入 MySQL
- 成功写入临时 Qdrant collection 并检索命中
- 测试数据已清理

说明：
- 当前对 LaTeX / 矢量图场景已支持 caption 锚点区域渲染

## 文档

- `docs/architecture.md`
- `docs/api-reference.md`
- `docs/implementation-status.md`
- `docs/learning-plan.md`
- `docs/retrieval-plan.md`
- `DATABASE_SCHEMA.md`
