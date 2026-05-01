from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"


def _build_env() -> dict[str, str]:
    """Build a dev environment with stable import paths for the flat src layout."""

    env = os.environ.copy()
    existing = [item for item in env.get("PYTHONPATH", "").split(os.pathsep) if item]
    pythonpath_entries = [str(ROOT), str(SRC_ROOT), *existing]
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(pythonpath_entries))
    return env


def main() -> int:
    command = [sys.executable, "-m", "uvicorn", "api.main:app", "--reload"]
    return subprocess.call(command, cwd=str(ROOT), env=_build_env())

# Build 项目环境变量，避免模块导入问题
if __name__ == "__main__":
    raise SystemExit(main())
