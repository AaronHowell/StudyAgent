"""PlanAgent loop for first-pass reproduction runs."""

from __future__ import annotations

from pathlib import Path

from workers.reproduce.locks import NullReproductionLock
from workers.reproduce.mailbox import FileMailbox
from workers.reproduce.models import ReproductionRun, RunEvent
from workers.reproduce.store import FileReproductionStore
from workers.reproduce.workers import BaseWorker


class PlanAgent:
    def __init__(
        self,
        *,
        store: FileReproductionStore,
        mailbox: FileMailbox,
        workers: list[BaseWorker],
        sandbox_root: Path | str,
        lock: object | None = None,
    ) -> None:
        self.store = store
        self.mailbox = mailbox
        self.workers = {worker.name: worker for worker in workers}
        self.sandbox_root = Path(sandbox_root)
        self.lock = lock or NullReproductionLock()

    async def create_run(
        self,
        *,
        project_id: str,
        objective: str,
        paper_ids: list[str],
        permission_mode: str = "manual",
    ) -> ReproductionRun:
        workspace = self.sandbox_root / "reproduction_runs" / project_id
        run = ReproductionRun.create(
            project_id=project_id,
            objective=objective,
            paper_ids=paper_ids,
            workspace_path=str(workspace),
            permission_mode=permission_mode,
        )
        workspace = self.sandbox_root / "reproduction_runs" / run.run_id / "workspace"
        run.workspace_path = str(workspace)
        run.report_path = str(workspace / "report.md")
        self.store.create(run)
        self.mailbox.ensure_mailboxes(run.run_id, list(run.agents))
        return run

    async def run(self, run_id: str) -> ReproductionRun:
        run = self.store.load(run_id)
        if run is None:
            raise ValueError(f"Reproduction run not found: {run_id}")
        if not self.lock.acquire_run(run_id):
            return run

        try:
            run.status = "running"

            while run.status not in {"completed", "failed", "cancelled", "paused"}:
                if run.current_iteration >= run.max_iterations:
                    run.status = "failed"
                    run.error = "max_iterations reached"
                    break

                self._apply_worker_results(run)
                ready_tasks = self._ready_tasks(run)
                if not ready_tasks:
                    if all(task.status == "completed" for task in run.tasks.values()):
                        run.status = "completed"
                        run.events.append(RunEvent.create("completed", "Reproduction run completed."))
                        break
                    run.status = "failed"
                    run.error = "No ready tasks and run is incomplete."
                    break

                for task in ready_tasks:
                    task.status = "running"
                    worker_name = task.assigned_to or self._worker_for_task(task.task_type)
                    task.assigned_to = worker_name
                    self.mailbox.send(
                        run_id=run.run_id,
                        sender="plan_agent",
                        recipient=worker_name,
                        message_type="task_assignment",
                        payload={"task_id": task.task_id},
                    )
                    worker = self.workers[worker_name]
                    await worker.tick(run)
                    self._apply_worker_results(run)

                run.current_iteration += 1
                self.store.save(run)

            self.store.save(run)
            return run
        finally:
            self.lock.release_run(run_id)

    def _apply_worker_results(self, run: ReproductionRun) -> None:
        messages = self.mailbox.read_unread(run.run_id, "plan_agent")
        for message in messages:
            if message.message_type != "task_result":
                continue
            task_id = str(message.payload["task_id"])
            task = run.tasks[task_id]
            if message.payload.get("status") == "completed":
                task.status = "completed"
                task.notes = str(message.payload.get("summary") or "")
                task.artifact_ids = [str(item) for item in message.payload.get("artifact_ids", [])]
                run.events.append(RunEvent.create("task_completed", task.notes, {"task_id": task_id}))
            else:
                task.attempts += 1
                task.status = "pending" if task.attempts < task.max_attempts else "failed"
            self.mailbox.mark_read(run.run_id, "plan_agent", [message.message_id])

    def _ready_tasks(self, run: ReproductionRun):
        return [
            task
            for task in run.tasks.values()
            if task.status == "pending"
            and all(run.tasks[blocked_id].status == "completed" for blocked_id in task.blocked_by)
        ]

    @staticmethod
    def _worker_for_task(task_type: str) -> str:
        if task_type in {"understand_paper", "extract_method"}:
            return "method_worker"
        if task_type == "inspect_figures":
            return "figure_worker"
        if task_type in {"design_reproduction", "create_project_files"}:
            return "code_worker"
        if task_type in {"run_experiment", "analyze_results"}:
            return "experiment_worker"
        return "report_worker"
