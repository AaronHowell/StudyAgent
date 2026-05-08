# PaperLab

PaperLab 是一个学术论文智能助手系统，支持论文检索、阅读、对话和知识管理。

项目分为两个顶层模块：

- `Desktop/` — React + Vite 前端
- `Server/` — FastAPI + LangGraph 编排后端
- `Docs/` — 结构说明与运行约束文档

## 目录结构

```text
PaperLab/
├── Desktop/
│   ├── src/
│   │   ├── components/
│   │   │   ├── chat/        # 对话面板、消息流、线程侧栏
│   │   │   ├── library/     # 论文库列表与卡片
│   │   │   ├── reader/      # 论文阅读器
│   │   │   └── layout/      # 布局组件
│   │   ├── hooks/           # 自定义 hooks
│   │   ├── usePaperLabStream.ts  # SSE 流式响应
│   │   └── styles.css
│   ├── package.json
│   └── vite.config.ts
└── Server/
    ├── api/                 # FastAPI 路由与 schemas
    │   ├── chat.py          # 对话 API
    │   ├── chat_turns.py    # 多轮对话管理
    │   └── routes/
    │       └── documents.py # 文档管理 API
    ├── src/
    │   ├── orchestration/   # LangGraph 编排核心
    │   │   ├── supervisor.py        # 总调度图
    │   │   ├── guidance_queue.py    # 线程级用户干预队列
    │   │   ├── graph_state.py       # 图状态定义
    │   │   ├── graph_messages.py    # 消息构建
    │   │   └── graph_serialization.py # 证据序列化
    │   ├── workers/
    │   │   ├── retriever/   # 检索 agent（工具调用模式）
    │   │   ├── tool/        # 工具执行 worker
    │   │   └── workspace/   # 编码 workspace worker
    │   ├── workspace/
    │   │   └── tools.py     # 跨平台文件/命令工具集
    │   ├── documents/       # PDF 解析与文档扫描
    │   ├── memory/          # LLM 驱动的长期记忆
    │   ├── prompts/         # Prompt 构建器
    │   ├── domain/          # 领域模型与端口
    │   ├── integrations/    # MySQL / Qdrant 存储
    │   ├── runtime/         # 依赖注入与取消令牌
    │   └── session_storage/ # 会话持久化
    ├── tests/
    ├── configs.py
    ├── dev.py               # 一键启动开发服务
    ├── pyproject.toml
    └── .env.example
```

## 主入口

| 入口 | 路径 |
|------|------|
| 前端 | `Desktop/src/main.tsx` |
| API | `Server/api/main.py` |
| 编排图 | `Server/src/orchestration/supervisor.py` |
| 项目文档 | `Docs/README.md` |

## 快速开始

### 后端

```bash
cd Server
uv sync
cp .env.example .env   # 填写 API keys 和数据库配置
uv run python dev.py   # 一键启动（带热重载）
```

或手动启动：

```bash
uv run uvicorn api.main:app --reload
```

### 前端

```bash
cd Desktop
npm install
npm run dev
```

## 架构概述

### 编排层

- **supervisor** 负责总编排：接收用户消息，派发检索任务，综合生成回答
- **retriever** 是核心检索 agent，基于 LangGraph 工具调用模式，支持多轮检索与证据收集
- **tool** worker 执行通用工具调用
- **guidance_queue** 提供线程级非阻塞用户干预能力

### 存储层

- MySQL 持久化文档元数据与会话
- Qdrant 向量库存储文档嵌入
- LLM 驱动的长期记忆服务

### 前端

- React + TypeScript + Vite
- SSE 流式对话响应
- 论文库管理、PDF 阅读器、多线程对话

## 当前约束

- 前端只连接 FastAPI，不直连 LangGraph Agent Server
- 只有 `supervisor` 读写长期记忆
- worker 只保留短期上下文
- workspace 能力通过工具模块提供，不再作为独立 agent
