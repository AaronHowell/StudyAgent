"""File-backed durable storage for reproduction runs."""

from __future__ import annotations

import json
from pathlib import Path

from workers.reproduce.models import ReproductionRun, RunEvent, utc_now


class FileReproductionStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def create(self, run: ReproductionRun) -> None:
        self._run_dir(run.run_id).mkdir(parents=True, exist_ok=True)
        Path(run.workspace_path).mkdir(parents=True, exist_ok=True)
        (Path(run.workspace_path) / "outputs" / "logs").mkdir(parents=True, exist_ok=True)
        self.save(run)

    def load(self, run_id: str) -> ReproductionRun | None:
        path = self._run_dir(run_id) / "run.json"
        if not path.exists():
            return None
        return ReproductionRun.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, run: ReproductionRun) -> None:
        run.updated_at = utc_now()
        run_dir = self._run_dir(run.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = run_dir / "run.json.tmp"
        tmp_path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(run_dir / "run.json")

    def list_runs(self, project_id: str | None = None) -> list[ReproductionRun]:
        runs = []
        if not self.root.exists():
            return runs
        for path in self.root.glob("*/run.json"):
            run = ReproductionRun.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if project_id is None or run.project_id == project_id:
                runs.append(run)
        runs.sort(key=lambda item: item.updated_at, reverse=True)
        return runs

    def append_event(self, run_id: str, event: RunEvent) -> None:
        run = self.load(run_id)
        if run is None:
            return
        run.events.append(event)
        self.save(run)

    def _run_dir(self, run_id: str) -> Path:
        return self.root / run_id
