# PaperLab

PaperLab 现在分成两个清晰的顶层部分：

- `Desktop/`：React + Vite 前端
- `Server/`：FastAPI + LangGraph 后端
- `Docs/`：当前结构、已验证功能和运行约束说明

## 目录

```text
PaperLab/
├── Desktop/
│   ├── package.json
│   └── src/
└── Server/
    ├── api/
    ├── configs/
    ├── src/
    ├── tests/
    ├── docs/
    ├── data/
    ├── pyproject.toml
    ├── langgraph.json
    └── .env.example
```

## 主入口

- Frontend main: `Desktop/src/main.tsx`
- API main: `Server/api/main.py`
- LangGraph main: `Server/src/orchestration/supervisor.py`
- Project docs: `Docs/README.md`

## 运行

```bash
cd Server
uv sync
uv run uvicorn api.main:app --reload
```

前端开发：

```bash
cd Desktop
npm install
npm run dev
```

LangGraph 图入口：

```bash
cd Server
langgraph dev
```

## 当前约束

- `supervisor` 负责总编排、并行派发、综合回答
- `retriever`、`tool`、`workspace` 是三个并行 worker
- 只有 `supervisor` 读写长期记忆
- worker 只保留短期上下文压缩
- 本地命令和文件写入必须通过 `workspace` 的 sandbox task
- benchmark、a2a、历史兼容 shim 均已从新项目移除
