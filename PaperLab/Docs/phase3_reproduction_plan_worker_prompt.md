# Phase 3 Prompt：实现 PLAN mode + Worker/Mailbox 的论文复现 Agent

你现在在本地 `StudyAgent` 工作区中工作。请在前两个阶段基础上完成 **第三阶段：论文复现功能**。

目标：当用户希望“尽可能复现论文”时，系统进入固定的 **PLAN mode**。PlanAgent 先制定计划，维护任务 DAG，然后通过 Worker 或轻量 Swarm-like Mailbox 模式分派任务，最终在本地 sandbox 中写代码、运行 Bash/PowerShell、保存日志和产物，生成复现报告。

请保持实现简单直接，不要做完整 Claude Code Swarm，不要过度抽象。这个项目是学习项目，代码可读性优先。

---

## 一、核心设计

采用固定结构：

```text
Reproduction Mode
  = PlanAgent
  + fixed WorkerAgents
  + per-agent Mailbox
  + Task DAG
  + Sandbox Workspace
  + CommandPolicy
  + optional LLM SafetyClassifier
```

不要让 LLM 动态创建 agent。

固定 agents：

```text
plan_agent
method_worker
figure_worker
code_worker
experiment_worker
report_worker
```

职责：

```text
PlanAgent:
  维护任务 DAG
  分派任务
  读取 worker 结果
  更新任务状态
  决定是否新增修复任务
  决定是否完成/失败/等待用户

MethodWorker:
  阅读论文正文证据
  提取方法、公式、模型结构、实验设置

FigureWorker:
  阅读图片/图表证据
  总结图表、caption、关键结果

CodeWorker:
  生成最小复现代码
  写 README、requirements、reproduce.py

ExperimentWorker:
  执行命令
  运行实验
  保存 stdout/stderr
  分析报错

ReportWorker:
  生成 report.md
```

---

## 二、不要做的事

不要：

- 不要实现完整 Swarm。
- 不要开 tmux。
- 不要多进程。
- 不要实现复杂 HookBus。
- 不要引入 Celery/Ray/Airflow。
- 不要让 LLM 动态创建 worker。
- 不要让 LLM 直接执行 shell。
- 不要在 sandbox 外写文件。
- 不要把长期 run 塞进普通 chat 请求里阻塞。
- 不要大规模重写现有问答流程。

第一版所有 worker 都在同一个 Python 进程内 async tick 即可。

---

## 三、目标目录

新增或完善：

```text
PaperLab/Server/src/workers/reproduce/
  __init__.py
  models.py
  store.py
  mailbox.py
  plan_agent.py
  workers.py
  command_policy.py
  safety_classifier.py

PaperLab/Server/src/generation/prompts/
  reproduce_planner.md
  reproduce_worker.md
  reproduce_evaluator.md
  reproduce_report.md

PaperLab/Server/api/routes/runs.py
```

如果第二阶段已经有部分文件，复用并扩展。

---

## 四、models.py

定义简单数据结构，使用 `dataclass(slots=True)`，不要用 Pydantic。

### ReproductionRun

字段：

```python
run_id: str
project_id: str
objective: str
paper_ids: list[str]
status: str
tasks: dict[str, PlanTask]
agents: dict[str, AgentState]
artifacts: dict[str, Artifact]
events: list[RunEvent]
workspace_path: str
report_path: str
permission_mode: str  # "manual" | "auto"
current_iteration: int
max_iterations: int
created_at: str
updated_at: str
error: str
```

status 允许：

```text
created
planning
running
waiting_for_user
paused
completed
failed
cancelled
```

### PlanTask

字段：

```python
task_id: str
title: str
description: str
task_type: str
status: str
assigned_to: str | None
blocked_by: list[str]
artifact_ids: list[str]
attempts: int
max_attempts: int
notes: str
```

status 允许：

```text
pending
running
completed
failed
blocked
skipped
```

### AgentState

字段：

```python
agent_name: str
status: str  # idle | busy | stopped
current_task_id: str | None
last_message_at: str | None
```

### Artifact

字段：

```python
artifact_id: str
artifact_type: str
path: str
summary: str
task_id: str | None
created_at: str
metadata: dict[str, object]
```

artifact_type 示例：

```text
paper_summary
method_summary
figure_summary
reproduction_plan
source_code
requirements
command_log
analysis
report
```

### MailboxMessage

字段：

```python
message_id: str
sender: str
recipient: str
message_type: str
payload: dict[str, object]
created_at: str
read: bool
```

message_type：

```text
task_assignment
task_result
status_update
request_permission
permission_response
plan_update
final_report
error
```

### RunEvent

字段：

```python
event_id: str
event_type: str
message: str
payload: dict[str, object]
created_at: str
```

所有模型提供：

```python
to_dict()
from_dict()
```

---

## 五、store.py

实现 `FileReproductionStore`。

存储结构：

```text
PaperLabCache/reproduction_runs/{run_id}/
  run.json
  events.jsonl
  workspace/
    README.md
    requirements.txt
    reproduce.py
    outputs/
      logs/
      figures/
      tables/
  artifacts/
  mailboxes/
    plan_agent.jsonl
    method_worker.jsonl
    figure_worker.jsonl
    code_worker.jsonl
    experiment_worker.jsonl
    report_worker.jsonl
```

方法：

```python
create(run: ReproductionRun) -> None
load(run_id: str) -> ReproductionRun | None
save(run: ReproductionRun) -> None
list_runs(project_id: str | None = None) -> list[ReproductionRun]
append_event(run_id: str, event: RunEvent) -> None
```

要求：

- `save()` 先写 `run.json.tmp`，再 replace。
- `load()` 文件不存在返回 None。
- 不要把 asyncio.Task 存进 JSON。
- 不要把图片 bytes、长日志、代码内容塞进 run.json。

---

## 六、mailbox.py

实现 per-agent mailbox。

方法：

```python
ensure_mailboxes(run_id: str, agent_names: list[str]) -> None

send(
    run_id: str,
    sender: str,
    recipient: str,
    message_type: str,
    payload: dict[str, object],
) -> MailboxMessage

read_unread(run_id: str, agent_name: str) -> list[MailboxMessage]

mark_read(run_id: str, agent_name: str, message_ids: list[str]) -> None
```

实现方式：

- 每个 agent 一个 jsonl 文件。
- 每个 agent 只读自己的 mailbox。
- `send()` append 一行 JSON。
- `read_unread()` 读取 `read=False` 的消息。
- `mark_read()` 可以重写该 agent 的 jsonl 文件，把对应消息 read 改为 true。
- 第一版不用复杂文件锁，但代码要简单稳定。

---

## 七、固定初始任务 DAG

`PlanAgent.create_run()` 创建初始任务：

```text
T1 understand_paper
T2 extract_method              blocked_by T1
T3 inspect_figures             blocked_by T1
T4 design_reproduction         blocked_by T2, T3
T5 create_project_files        blocked_by T4
T6 run_experiment              blocked_by T5
T7 analyze_results             blocked_by T6
T8 write_report                blocked_by T7
```

任务说明：

### T1 understand_paper

Worker：`method_worker`

输出：

```text
paper_understanding.md
```

内容：

- 论文目标
- 核心问题
- 主要贡献
- 实验目标
- 可复现范围

### T2 extract_method

Worker：`method_worker`

输出：

```text
method_summary.md
```

内容：

- 模型结构
- 算法步骤
- 关键公式
- 损失函数
- 输入输出
- 训练/评估设置

### T3 inspect_figures

Worker：`figure_worker`

输出：

```text
figures_summary.md
```

内容：

- 图表列表
- 每张图的 caption/summary
- 与复现相关的图
- 需要对比的指标或趋势

### T4 design_reproduction

Worker：`code_worker`

输出：

```text
reproduction_plan.md
```

内容：

- 最小复现目标
- 需要实现的模块
- 是否使用 synthetic/toy data
- 运行命令
- 预期输出

### T5 create_project_files

Worker：`code_worker`

输出：

```text
README.md
requirements.txt
reproduce.py
```

### T6 run_experiment

Worker：`experiment_worker`

执行：

```text
python reproduce.py
```

输出：

```text
outputs/logs/run_experiment.log
```

### T7 analyze_results

Worker：`experiment_worker`

输出：

```text
analysis.md
```

内容：

- 运行是否成功
- 输出结果
- 与论文结果差异
- 报错原因或限制

### T8 write_report

Worker：`report_worker`

输出：

```text
report.md
```

内容：

- 复现目标
- 使用的论文证据
- 实现了什么
- 运行结果
- 失败/限制
- 生成的文件列表
- 下一步建议

---

## 八、plan_agent.py

实现 `PlanAgent`。

构造函数建议：

```python
class PlanAgent:
    def __init__(
        self,
        store: FileReproductionStore,
        mailbox: Mailbox,
        workers: list[BaseWorker],
        retrieve_evidence_use_case=None,
        llm_provider=None,
        sandbox_root: Path | None = None,
    ):
        ...
```

方法：

```python
async def create_run(
    self,
    project_id: str,
    objective: str,
    paper_ids: list[str],
    evidence_pack: object | None = None,
    permission_mode: str = "manual",
) -> ReproductionRun:
    ...

async def run(self, run_id: str) -> ReproductionRun:
    ...
```

主循环：

```python
while run.status not in {"completed", "failed", "cancelled"}:
    if run.status == "paused":
        save and return

    if run.current_iteration >= run.max_iterations:
        run.status = "failed"
        run.error = "max_iterations reached"
        save and return

    read plan_agent mailbox
    apply task_result messages

    ready_tasks = find tasks where:
      status == "pending"
      all blocked_by tasks are completed

    if no ready tasks:
      if all tasks completed:
          run.status = "completed"
          save and return
      if any failed critical task:
          run.status = "failed"
          save and return
      else:
          run.status = "waiting_for_user"
          save and return

    for each ready task:
        choose worker
        set task.status = "running"
        set task.assigned_to = worker
        send task_assignment to worker mailbox

    tick each worker once

    current_iteration += 1
    save
```

`apply task_result`：

- completed：
  - task.status = completed
  - attach artifact_ids
  - task.notes = summary

- failed：
  - task.attempts += 1
  - 如果 attempts < max_attempts：
    - 可以把 task.status 重新设 pending
    - 或新增 fix_error task
  - 否则 task.status = failed

第一版可以简单：失败后重试一次，超过就 failed。

---

## 九、workers.py

实现：

```python
class BaseWorker:
    name: str

    async def tick(self, run: ReproductionRun) -> None:
        messages = mailbox.read_unread(run.run_id, self.name)
        for msg in messages:
            if msg.message_type == "task_assignment":
                await self.handle_task(run, task)
                mailbox.mark_read(...)
```

每个 worker 完成后发送：

```python
mailbox.send(
    run_id=run.run_id,
    sender=self.name,
    recipient="plan_agent",
    message_type="task_result",
    payload={
        "task_id": task.task_id,
        "status": "completed" | "failed",
        "summary": "...",
        "artifact_ids": [...],
        "error": "",
    },
)
```

### MethodWorker

- `understand_paper`
- `extract_method`

可以从 evidence_pack / task description / paper_ids 生成 markdown。
如果没有真实 evidence_pack，生成 fallback summary，并说明证据不足。

### FigureWorker

- `inspect_figures`

使用 EvidencePack.assets / asset captions / asset summaries。
输出 `figures_summary.md`。

### CodeWorker

- `design_reproduction`
- `create_project_files`

`create_project_files` 至少生成：

```python
# reproduce.py
from pathlib import Path
import json
import random

def main():
    outputs = Path("outputs")
    outputs.mkdir(exist_ok=True)
    result = {
        "status": "ok",
        "message": "Minimal reproduction scaffold executed.",
        "note": "This is a toy/synthetic reproduction scaffold."
    }
    (outputs / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
```

### ExperimentWorker

- `run_experiment`
- `analyze_results`

执行命令必须经过 `CommandPolicy` 和可选 `SafetyClassifier`。

运行命令：

```text
python reproduce.py
```

cwd 必须是 run.workspace_path。

保存日志到：

```text
workspace/outputs/logs/run_experiment.log
```

### ReportWorker

- `write_report`

读取已有 markdown artifacts 和日志，生成 `report.md`。

---

## 十、command_policy.py

实现确定性安全规则。

```python
CommandDecision = "allow" | "deny" | "require_user"
```

直接 allow：

```text
python reproduce.py
pytest
pip install -r requirements.txt
ls
cat
grep
rg
find
pwd
python --version
pip --version
```

直接 deny：

```text
cwd outside workspace
rm -rf /
rm -rf ~
sudo
su
chmod -R 777
chown
curl ... | sh
wget ... | bash
git push
git reset --hard
```

其他：

```text
require_user
```

要求：

- 规则简单可读。
- 宁可保守 require_user。
- 不要追求完整 shell parser。
- 确定性 deny 不能被 LLM 推翻。

---

## 十一、safety_classifier.py

实现类似 Claude Code auto mode 的轻量 LLM 安全检查。

只处理 `CommandPolicy` 返回 `require_user` 的情况。

输入：

```python
SafetyClassificationRequest:
    command
    cwd
    workspace_path
    objective
    task_title
    task_description
    recent_notes
```

输出：

```python
SafetyClassificationResult:
    should_allow: bool
    reason: str
```

Prompt 要求：

```text
You are a safety classifier for PaperLab reproduction auto mode.
Decide whether the command can be automatically executed without asking the user.

Allow only if:
- command runs inside sandbox workspace
- command is relevant to the reproduction task
- command does not delete user data
- command does not access secrets
- command does not modify system/global config
- command does not download and execute remote scripts

Block if uncertain.

Return JSON only:
{
  "should_allow": true/false,
  "reason": "one short sentence"
}
```

要求：

- JSON 解析失败默认 block。
- classifier 不能执行命令。
- classifier 不能覆盖 deterministic deny。
- classification result 要写入 task notes 或 run event。

---

## 十二、API：api/routes/runs.py

实现最小 API。

### POST `/runs/reproduce`

输入：

```json
{
  "project_id": "frontend-project",
  "objective": "尽可能复现这篇论文",
  "paper_ids": ["..."],
  "permission_mode": "manual"
}
```

行为：

- 创建 ReproductionRun
- 后台启动 PlanAgent.run(run_id)
- 立即返回：

```json
{
  "run_id": "...",
  "status": "running",
  "workspace_path": "...",
  "report_path": "..."
}
```

### GET `/runs/{run_id}`

返回：

- run_id
- status
- objective
- tasks
- artifacts
- report_path
- error

### GET `/runs/{run_id}/events`

第一版返回 JSON list：

```json
[
  {
    "event_type": "...",
    "message": "...",
    "created_at": "..."
  }
]
```

暂时不做 SSE。

### POST `/runs/{run_id}/pause`

设置 `paused`。

### POST `/runs/{run_id}/resume`

重新后台启动 `PlanAgent.run(run_id)`。

### POST `/runs/{run_id}/cancel`

设置 `cancelled`。

要求：

- 不阻塞 HTTP 请求等待复现完成。
- 后台 task handle 可以先存在简单 runtime dict 中。
- 不要引入 Celery。
- 如果服务重启，用户可以通过 resume 继续。

---

## 十三、和现有问答系统的关系

普通论文问答继续走：

```text
retrieval -> answer
```

论文复现走：

```text
POST /runs/reproduce -> PlanAgent background run
```

不要把长期复现 loop 塞进普通 `/agent/answer/stream`。

如果容易，可以在 chat/supervisor route 中检测：

```text
复现
reproduce
implement paper
run experiment
写代码验证论文
```

然后返回提示或自动创建 run。

但第一版最重要的是 `/runs/reproduce` 可用。

---

## 十四、证据使用

PlanAgent / Worker 应使用第二阶段的 EvidencePack：

- text chunks
- asset captions
- asset summaries
- asset citations
- optional image evidence metadata

第一版不要求 worker 再调用 vision model 看图片。
但 FigureWorker 至少要使用 asset caption/summary/page/document_id 生成 `figures_summary.md`。

复现报告中要写：

```text
Used evidence:
- [C1] ...
- [A1] ...
```

如果没有足够证据，必须说明：

```text
This is a minimal/toy reproduction scaffold because the paper does not provide enough implementation details or dataset access.
```

---

## 十五、测试要求

新增测试：

```text
tests/unit/test_reproduce_models.py
tests/unit/test_reproduce_store.py
tests/unit/test_mailbox.py
tests/unit/test_command_policy.py
tests/unit/test_safety_classifier.py
tests/unit/test_plan_agent_smoke.py
tests/unit/test_runs_api_import.py
```

Smoke test：

1. 创建 fake EvidencePack。
2. create run。
3. run PlanAgent。
4. worker 收到 task。
5. 生成 `README.md`、`requirements.txt`、`reproduce.py`。
6. 执行 `python reproduce.py`。
7. 生成 log。
8. 生成 `report.md`。
9. run.status 最终是 `completed` 或明确 `failed`，但不能崩溃。

Command policy test：

- `rm -rf ~` -> deny
- `sudo apt install` -> deny
- `python reproduce.py` in workspace -> allow
- cwd outside workspace -> deny
- unknown command -> require_user

Safety classifier test：

- fake LLM 返回 allow
- fake LLM 返回 block
- JSON parse fail -> block
- deterministic deny 不调用 classifier

---

## 十六、阶段完成标准

第三阶段完成后：

1. 可以通过 API 创建论文复现 run。
2. PlanAgent 创建固定任务 DAG。
3. Worker 通过 mailbox 收发任务。
4. CodeWorker 生成最小复现项目。
5. ExperimentWorker 在 workspace 中执行 `python reproduce.py`。
6. 命令执行前经过 CommandPolicy。
7. `permission_mode=auto` 时不确定命令可交给 SafetyClassifier。
8. 生成 logs、analysis、report。
9. run 状态可查询，可 pause/resume/cancel。
10. 代码简单直接，适合学习。
