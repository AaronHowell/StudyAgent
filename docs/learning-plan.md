# Learning Plan

## 已完成阶段

### Phase A: 骨架与契约

已完成：
- 目录分层
- 领域模型
- 端口定义
- 最小 API / 前端壳层

### Phase B: 文档处理

已完成：
- 目录扫描
- PDF 元数据提取
- 页文本解析
- 视觉资产提取基础版
- 文本分块

### Phase C: 数据落地

已完成：
- MySQL repositories
- Qdrant vector store
- Embedding provider
- `IngestDocumentUseCase`
- 后台入库任务管理

### Phase D: 前端工作台

已完成：
- React + Vite 前端迁移
- 文档库模式
- PDF 阅读页面
- 图表画廊
- 入库任务面板

## 下一阶段

### Phase E: Retrieval 基础能力

目标：
- 从“已入库”进入“可检索”

建议任务：
1. 做文档级检索
   - 使用 `DocumentProfile`
2. 做正文 chunk 检索
3. 做视觉资产检索
4. 组装统一 `EvidencePack`
5. 给后续 LangGraph Retrieval Agent 预留统一输入输出

### Phase F: LangGraph Agent 主链

目标：
- 搭建最小 Planner / Retrieval / Writer / Critic 流程

建议任务：
1. 定义 graph state
2. 先接 Retrieval Agent
3. 再接 Writer
4. 最后加 Critic 回路

### Phase G: SOLO 模式

目标：
- 将前端 SOLO 模式接成真正的 Agent 对话界面

建议任务：
1. 设计聊天协议
2. 设计上下文注入
3. 共享当前选中文档 / 当前项目

## 当前优先级建议

优先顺序：

1. Retrieval 能力
2. 文档级 / chunk / asset 三层检索联调
3. EvidencePack 组装
4. LangGraph 最小图
5. SOLO 模式对话

## 暂不优先

- RabbitMQ / Celery
- 分布式任务系统
- Redis 记忆系统完整实现
- 复杂权限体系
- 多用户支持

参考设计文档：
- `docs/retrieval-plan.md`
