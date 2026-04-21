# PaperLab Docs

## Current Scope

PaperLab is currently split into two top-level applications:

- `Desktop/`: the React + Vite frontend
- `Server/`: the FastAPI + LangGraph backend

The backend keeps one supervisor agent and three workers:

- `retriever`: paper and evidence retrieval
- `tool`: web and MCP-backed external tools
- `workspace`: repository inspection plus task-scoped local execution

Only the supervisor keeps long-term memory. The three workers only receive short-term compressed context.

## Main Entrypoints

- Frontend main: `Desktop/src/main.tsx`
- API main: `Server/api/main.py`
- LangGraph main: `Server/src/orchestration/supervisor.py`

## Current Verified Functions

The current PaperLab tree has been checked for these behaviors:

- backend entrypoints import correctly
- `GET /healthz` returns `200`
- frontend builds successfully with Vite
- sandbox task creation works
- sandbox command execution respects the command whitelist
- sandbox file reads and writes stay inside the task workspace

## Sandbox Model

Local execution now goes through task-scoped run environments under:

```text
PaperLab/Server/data/runs/<task_id>/
├── workspace/
├── logs/
├── outputs/
└── metadata.json
```

The system owns the task root structure. The model is free to create any internal layout under `workspace/`.

Current workspace-task tools:

- `create_run_task`
- `run_task_command`
- `read_task_file`
- `write_task_file`
- `list_task_files`
- `finish_task`

Repository files remain readable for inspection, but local writes and command execution are restricted to task workspaces.

## Run

Backend:

```bash
cd Server
uv sync
uv run uvicorn api.main:app --reload
```

Frontend:

```bash
cd Desktop
npm install
npm run dev
```
