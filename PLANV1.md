# 科研论文助手 V1 迭代式学习方案

## Summary
项目按“可扩展、可读、可学习”三条原则设计，不追求一次做全。  
第一阶段只实现能稳定跑通的主链路：`项目 -> 文档入库 -> 检索 -> 多 Agent 回答 -> 引用 -> 基础记忆 -> 桌面端展示`。  
实现方式采用 `Tauri 2 + Vue 3 + TypeScript`、`FastAPI`、`LangGraph`、`MySQL + Qdrant + Redis`。  
开发方式采用“你主实现，我辅导”的节奏：每次只做一个明确子系统，我负责拆任务、解释关键设计、审查你的代码、补足卡点，不直接一次性替你写完整项目。

## Implementation Changes
### 1. 架构原则
- 采用“核心域逻辑 + 基础设施适配层”结构，避免把 LangGraph、数据库、模型 SDK 直接写进业务逻辑。
- 所有核心能力都先定义接口，再接实现，便于后续替换：
  - `LLMProvider`
  - `EmbeddingProvider`
  - `VectorStore`
  - `MemoryStore`
  - `DocumentParser`
  - `WebSearchProvider`
- Agent 流程中的状态、任务卡、证据包、引用对象全部用 `Pydantic` 显式建模。
- 不做过度抽象，不上插件系统 v1；但目录和接口要预留扩展点。

### 2. 推荐目录
- `apps/desktop`
  - Tauri + Vue 前端，只负责 UI、配置、流式展示、本地目录选择。
- `apps/api`
  - FastAPI 服务，只负责接口、任务调度、LangGraph 编排。
- `packages/domain`
  - 核心数据结构、接口定义、业务规则，不依赖具体框架。
- `packages/rag`
  - 文档解析、切块、索引、检索、重排。
- `packages/agents`
  - Planner / Retrieval / Writer / Critic 节点与图编排。
- `packages/memory`
  - 短期记忆、长期记忆、记忆摘要与写回策略。
- `packages/integrations`
  - Qdrant、MySQL、Redis、DuckDuckGo、OpenAI-compatible 适配器。
- `docs/`
  - 架构说明、数据流、开发笔记；每做完一个模块就补文档。

### 3. 明确哪些部分你自己实现
这些部分建议你亲手实现，我只做设计指导、伪代码、代码审查和局部补丁：
- 核心数据模型
  - `Project`、`Document`、`Chunk`、`Citation`、`TaskCard`、`EvidencePack`、`MemoryItem`
- 文档入库主链路
  - 扫描目录、文件去重、增量更新、分块元数据设计
- LangGraph 主流程
  - 状态定义、节点输入输出、条件跳转
- 检索主逻辑
  - 本地召回、证据组装、引用定位
- 记忆主逻辑
  - 会话摘要写回、项目级长期记忆读取与过滤
- API 契约
  - 请求响应 schema、流式事件 schema
- 前端核心页面
  - 项目页、聊天页、索引状态页、引用面板

这些部分可以先用成熟库，后续再逐步替换或深入：
- PDF 解析底层库
- OCR
- DuckDuckGo 搜索封装
- 基础 rerank
- Tauri 壳层能力
- 数据库连接与迁移工具

### 4. V1 功能边界
- 支持单用户。
- 支持 `PDF + Markdown`。
- 每个项目绑定一个本地文档库目录。
- 桌面端本地运行，后端本地运行，数据库用远端 `10.201.0.86`。
- 模型统一走 OpenAI-compatible API。
- 联网检索按需触发，不默认开启。
- 记忆只做两层：
  - 短期记忆：当前会话和最近证据摘要
  - 长期记忆：项目级研究结论、偏好、历史问答摘要
- Skills / MCP / Subagent / Shell 只预留扩展位，不进入首版主线。

### 5. 多 Agent 设计
- `Planner`
  - 输入：问题、项目摘要、相关长期记忆摘要
  - 输出：固定结构任务卡
- `Retrieval`
  - 输入：任务卡
  - 输出：证据包
  - 优先本地库，不足再触发 DuckDuckGo
- `Writer`
  - 输入：问题、证据包、输出格式
  - 输出：必须带引用的答案
- `Critic`
  - 检查是否缺引用、是否证据不足、是否偏题
  - 输出 `pass / revise / retrieve_more`
- `Coordinator`
  - 负责图编排和上下文裁剪
  - 不传递完整历史，只传摘要和结构化对象

### 6. 为后续扩展预留但当前不实现
- 多文档格式扩展：`docx/html/notion export`
- 多项目全局搜索
- 文献关系图谱
- 引用导出 `BibTeX/RIS`
- Skills 与 MCP 工具注册
- Shell 白名单工具
- 多用户体系
- 本地/远端双模式部署切换

## Learning Workflow
### 1. 开发节奏
按下面顺序一块一块做，每完成一块再进入下一块：
1. 项目骨架与目录
2. 核心数据模型
3. 文档扫描与入库元数据
4. PDF/Markdown 分块
5. Qdrant 索引与检索
6. FastAPI 基础接口
7. LangGraph 单轮问答链路
8. 引用系统
9. 短期记忆
10. 长期记忆
11. DuckDuckGo 补检索
12. Tauri 前端接入
13. Critic 回路与稳定性优化

### 2. 我对你的支持方式
每一轮都按固定方式协作：
- 先解释这一轮为什么这么设计。
- 给你非常小的实现目标。
- 明确你要写哪些文件、哪些类、哪些函数。
- 给你接口定义、伪代码、验收标准。
- 你完成后，我帮你 review，并指出命名、结构、边界问题。
- 只在你卡住或你明确要求时，我再补具体代码。

### 3. 编码要求
- 单个模块先写清楚接口和数据结构，再写实现。
- 核心函数保持短小，复杂逻辑拆 helper。
- 每个模块都写 README 或设计注释，解释“职责”和“为什么这样分层”。
- 命名优先清晰，不追求炫技。
- 每个阶段都保证“当前代码可运行”。

## Test Plan
- 每个模块都要有最小验收，不等到最后一起测。
- 文档入库
  - 新文件可识别、重复文件不重复入库、删除后状态正确。
- 分块与索引
  - PDF/Markdown 能稳定产出 chunk，chunk 元数据完整。
- 检索
  - 给定问题能返回相关 chunk，并能定位来源。
- Agent 流程
  - Planner 输出合法任务卡。
  - Writer 输出必须带引用。
  - Critic 能拒绝无引用答案。
- 记忆
  - 新会话能读到同项目长期记忆。
  - 不同项目记忆不串。
- 前端
  - 可创建项目、选择目录、发起问答、看到流式结果和引用。

## Assumptions
- 这是学习项目，优先代码清晰和可理解，不优先极致性能。
- 你希望逐步实现，而不是让我一次性生成完整工程。
- 首版不追求高级插件生态，只保证主链路设计不堵死后续扩展。
- 首版不引入过多框架魔法，尽量保留可读、可调试、可替换的实现。

