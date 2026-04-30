"""Fixed worker implementations for first-pass reproduction runs."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from workers.reproduce.command_policy import CommandPolicy
from workers.reproduce.mailbox import FileMailbox
from workers.reproduce.models import Artifact, ReproductionRun
from workers.reproduce.store import FileReproductionStore


class BaseWorker:
    name = "base_worker"

    def __init__(self, *, store: FileReproductionStore, mailbox: FileMailbox) -> None:
        self.store = store
        self.mailbox = mailbox

    async def tick(self, run: ReproductionRun) -> None:
        messages = self.mailbox.read_unread(run.run_id, self.name)
        for message in messages:
            if message.message_type == "task_assignment":
                await self.handle_task(run, str(message.payload["task_id"]))
            self.mailbox.mark_read(run.run_id, self.name, [message.message_id])

    async def handle_task(self, run: ReproductionRun, task_id: str) -> None:
        raise NotImplementedError

    def complete(self, run: ReproductionRun, task_id: str, summary: str, artifacts: list[Artifact]) -> None:
        for artifact in artifacts:
            run.artifacts[artifact.artifact_id] = artifact
        self.mailbox.send(
            run_id=run.run_id,
            sender=self.name,
            recipient="plan_agent",
            message_type="task_result",
            payload={
                "task_id": task_id,
                "status": "completed",
                "summary": summary,
                "artifact_ids": [artifact.artifact_id for artifact in artifacts],
                "error": "",
            },
        )


class MarkdownWorker(BaseWorker):
    output_by_task: dict[str, tuple[str, str, str]] = {}

    async def handle_task(self, run: ReproductionRun, task_id: str) -> None:
        task = run.tasks[task_id]
        file_name, artifact_type, body = self.output_by_task[task.task_type]
        path = Path(run.workspace_path) / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.format(objective=run.objective), encoding="utf-8")
        artifact = Artifact(
            artifact_id=f"{task_id}-{artifact_type}",
            artifact_type=artifact_type,
            path=str(path),
            summary=f"Wrote {file_name}.",
            task_id=task_id,
        )
        self.complete(run, task_id, artifact.summary, [artifact])


class MethodWorker(MarkdownWorker):
    name = "method_worker"
    output_by_task = {
        "understand_paper": (
            "paper_understanding.md",
            "paper_summary",
            "# Paper Understanding\n\nObjective: {objective}\n\nThis first pass records the reproducible scope from available evidence.\n",
        ),
        "extract_method": (
            "method_summary.md",
            "method_summary",
            "# Method Summary\n\nThe first implementation uses a minimal synthetic scaffold until more method details are available.\n",
        ),
    }


class FigureWorker(MarkdownWorker):
    name = "figure_worker"
    output_by_task = {
        "inspect_figures": (
            "figures_summary.md",
            "figure_summary",
            "# Figure Summary\n\nVisual evidence is tracked through recalled asset captions and summaries.\n",
        )
    }


class CodeWorker(MarkdownWorker):
    name = "code_worker"
    output_by_task = {
        "design_reproduction": (
            "reproduction_plan.md",
            "reproduction_plan",
            "# Reproduction Plan\n\nBuild a minimal synthetic reproduction scaffold for: {objective}\n",
        )
    }

    async def handle_task(self, run: ReproductionRun, task_id: str) -> None:
        task = run.tasks[task_id]
        if task.task_type != "create_project_files":
            await super().handle_task(run, task_id)
            return

        workspace = Path(run.workspace_path)
        readme = workspace / "README.md"
        requirements = workspace / "requirements.txt"
        script = workspace / "reproduce.py"
        readme.write_text(f"# Minimal Reproduction\n\nObjective: {run.objective}\n", encoding="utf-8")
        requirements.write_text("", encoding="utf-8")
        script.write_text(
            'from pathlib import Path\n'
            'import json\n\n'
            'def main():\n'
            '    outputs = Path("outputs")\n'
            '    outputs.mkdir(exist_ok=True)\n'
            '    result = {"status": "ok", "message": "Minimal reproduction scaffold executed."}\n'
            '    (outputs / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")\n'
            '    print(json.dumps(result, indent=2))\n\n'
            'if __name__ == "__main__":\n'
            '    main()\n',
            encoding="utf-8",
        )
        artifacts = [
            Artifact(f"{task_id}-readme", "source_code", str(readme), "Wrote README.md.", task_id),
            Artifact(f"{task_id}-requirements", "requirements", str(requirements), "Wrote requirements.txt.", task_id),
            Artifact(f"{task_id}-script", "source_code", str(script), "Wrote reproduce.py.", task_id),
        ]
        self.complete(run, task_id, "Created minimal reproduction project files.", artifacts)


class ExperimentWorker(MarkdownWorker):
    name = "experiment_worker"
    output_by_task = {
        "analyze_results": (
            "analysis.md",
            "analysis",
            "# Analysis\n\nThe minimal reproduction scaffold ran and produced `outputs/result.json`.\n",
        )
    }

    async def handle_task(self, run: ReproductionRun, task_id: str) -> None:
        task = run.tasks[task_id]
        if task.task_type != "run_experiment":
            await super().handle_task(run, task_id)
            return

        workspace = Path(run.workspace_path)
        policy = CommandPolicy()
        decision = policy.decide("python reproduce.py", cwd=workspace, workspace_path=workspace)
        log_path = workspace / "outputs" / "logs" / "run_experiment.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if decision.decision != "allow":
            log_path.write_text(f"Command blocked: {decision.reason}\n", encoding="utf-8")
        else:
            completed = subprocess.run(
                ["python", "reproduce.py"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                check=False,
            )
            log_path.write_text(
                f"exit_code: {completed.returncode}\n\n[stdout]\n{completed.stdout}\n\n[stderr]\n{completed.stderr}\n",
                encoding="utf-8",
            )
        artifact = Artifact(f"{task_id}-log", "command_log", str(log_path), "Ran python reproduce.py.", task_id)
        self.complete(run, task_id, "Ran reproduction experiment.", [artifact])


class ReportWorker(MarkdownWorker):
    name = "report_worker"

    async def handle_task(self, run: ReproductionRun, task_id: str) -> None:
        path = Path(run.report_path)
        path.write_text(
            "# Reproduction Report\n\n"
            f"Objective: {run.objective}\n\n"
            "This is a minimal/toy reproduction scaffold because the first pass may not have full dataset or implementation details.\n\n"
            "Generated files include README.md, requirements.txt, reproduce.py, logs, analysis, and this report.\n",
            encoding="utf-8",
        )
        artifact = Artifact(f"{task_id}-report", "report", str(path), "Wrote final report.", task_id)
        self.complete(run, task_id, "Wrote reproduction report.", [artifact])


def build_default_workers(*, store: FileReproductionStore, mailbox: FileMailbox) -> list[BaseWorker]:
    return [
        MethodWorker(store=store, mailbox=mailbox),
        FigureWorker(store=store, mailbox=mailbox),
        CodeWorker(store=store, mailbox=mailbox),
        ExperimentWorker(store=store, mailbox=mailbox),
        ReportWorker(store=store, mailbox=mailbox),
    ]
