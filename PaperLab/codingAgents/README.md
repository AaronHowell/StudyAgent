# CodingAgents

论文复现 Coding Agent 模块，参考 OpenCode / Claude Code 设计。

## 架构

```
codingAgents/
├── backend/
│   ├── src/
│   │   ├── agent/          # 核心 Agent 循环
│   │   │   ├── loop.py     # Agent 主循环（读论文 → 生成代码 → 执行 → 修复）
│   │   │   ├── planner.py  # 复现计划生成
│   │   │   └── state.py    # Agent 状态管理
│   │   ├── container/      # Docker 沙箱
│   │   │   ├── manager.py  # 容器生命周期管理
│   │   │   └── sandbox.py  # 沙箱执行环境
│   │   ├── tools/          # Agent 工具集
│   │   │   ├── file_ops.py # 文件读写/编辑
│   │   │   ├── executor.py # 代码执行
│   │   │   ├── searcher.py # 代码搜索
│   │   │   └── registry.py # 工具注册
│   │   └── api/            # FastAPI 路由
│   │       ├── routes.py   # API 端点
│   │       └── schemas.py  # 请求/响应模型
│   ├── configs/
│   │   └── settings.py     # 配置管理
│   ├── pyproject.toml
│   └── main.py             # 入口
└── frontend/               # 前端组件（集成到 Desktop）
```

## 设计原则

1. **Approve 模式**: 每个 Agent 动作需要用户确认
2. **Docker 隔离**: 代码在容器中执行，不影响宿主机
3. **LLM 驱动**: 使用 OpenClaw 配置的 LLM
4. **论文感知**: 结合检索系统获取论文上下文
5. **自主修复**: 代码出错时自动分析并修复

## 启动

```bash
cd backend
uv sync
uv run python main.py
```
