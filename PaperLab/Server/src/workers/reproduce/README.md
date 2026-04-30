# Reproduction Mode

PaperLab reproduction mode uses a fixed initial task graph that the planner can
extend with repair or follow-up tasks.

- PlanAgent owns the run and task DAG.
- Worker agents are fixed: method, figure, code, experiment, report.
- Mailboxes persist messages for each agent.
- Command execution stays inside a sandbox workspace.
- CommandPolicy is deterministic and cannot be bypassed by LLM output.
- Redis may provide locks and coordination; files remain the durable state.
