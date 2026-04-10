# Architecture Overview

## 当前目标

当前项目重点不是 Agent 推理本身，而是先完成科研论文工作台的知识底座：
- 扫描本地论文库
- 解析 PDF
- 提取正文与视觉资产
- 分块
- 入库 MySQL
- 写入 Qdrant
- 提供桌面端可用的阅读与入库工作流

## 分层结构

### `packages/domain`

放核心模型和抽象接口：
- `Document`
- `DocumentAsset`
- `Chunk`
- `DocumentProfile`
- repository / provider / vector store ports

这一层不依赖具体数据库、HTTP SDK、Qdrant 客户端。

### `packages/documents`

放文档处理能力：
- `LocalDocumentScanner`
- `PdfParser`
- `TextChunkBuilder`

负责：
- 发现 PDF
- 提取页文本
- 提取视觉资产
- 分块

### `packages/application`

放应用层用例：
- `IngestDocumentUseCase`

职责：
- 组织“解析 -> 分块 -> MySQL -> Qdrant”这条完整业务链

### `packages/integrations`

放外部系统适配器：
- MySQL repositories
- Qdrant vector store
- OpenAI-compatible embedding provider

### `apps/api`

FastAPI 壳层，负责：
- 装配依赖
- 暴露 API
- 管理后台入库任务

### `apps/desktop`

React + Vite 桌面前端，负责：
- 文档库页面
- PDF 阅读
- 视觉资产画廊
- 入库任务面板
- 后续 SOLO / Agent 模式入口

## 当前数据流

### 文档入库

1. 前端选择目录并调用 `/documents/scan`
2. API 使用 `LocalDocumentScanner` 发现 PDF
3. 用户触发单篇或批量入库
4. `IngestionTaskManager` 在后台线程执行任务
5. `IngestDocumentUseCase` 调用：
   - `PdfParser`
   - `TextChunkBuilder`
   - MySQL repositories
   - Embedding provider
   - Qdrant vector store
6. 前端轮询任务状态

### 检索分层

Qdrant 当前分三层索引：
- `documents`
  - 文档级画像，先找相关论文
- `chunks`
  - 正文 chunk，找具体证据
- `assets`
  - 视觉资产摘要，找图表证据

## 当前并发模型

并发调度由 `IngestionTaskManager` 负责：
- `ThreadPoolExecutor`
- 同一路径去重
- 软超时
- 结构化错误分类
- API 退出时优雅关闭

说明：
- 这是单进程轻量任务管理，不是分布式队列系统
- 当前阶段不引入 RabbitMQ / Celery

## 当前限制

- 入库任务超时是软超时，不会强杀线程
- 视觉资产提取仍偏 embedded image 和启发式回退
- 还未接入 LangGraph Agent 主流程
- 还未接入 Redis 记忆系统
- 还未做真正多模态图片 embedding
