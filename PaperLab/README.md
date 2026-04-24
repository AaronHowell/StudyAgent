# PaperLab

PaperLab 现在分成两个清晰的顶层部分：

- `Desktop/`：React + Vite 前端
- `Server/`：FastAPI + LangGraph 编排后端
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
    ├── pyproject.toml
    ├── dev.py
    └── .env.example
```

## 主入口

- Frontend main: `Desktop/src/main.tsx`
- API main: `Server/api/main.py`
- Graph main: `Server/src/orchestration/supervisor.py`
- Project docs: `Docs/README.md`

## 运行

```bash
cd Server
uv sync
uv run uvicorn api.main:app --reload
```

一键启动后端开发服务：

```bash
cd Server
uv sync
uv run python dev.py
```

前端开发：

```bash
cd Desktop
npm install
npm run dev
```

LangGraph 图入口：

## 当前约束

- `supervisor` 负责总编排、并行派发、综合回答
- `retriever`、`tool`、`workspace` 是三个并行 worker
- 只有 `supervisor` 读写长期记忆
- worker 只保留短期上下文压缩
- 前端只连接 FastAPI，不再直连 LangGraph Agent Server
- 本地命令和文件写入必须通过 `workspace` 的 sandbox task
- benchmark、a2a、历史兼容 shim 均已从新项目移除
