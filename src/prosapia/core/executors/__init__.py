"""Executors: run a tool's task script once per manifest line on some scheduler.

The manifest and the task script (``<tool>.sh``) are the scheduler-agnostic tool
contract: task N reads manifest line N (via ``SAPIA_TASK_ID`` in the prelude). An
executor is a plain function ``ExecutorFn(ctx) -> None`` that owns only the
scheduling -- how the manifest is split and how each task gets launched.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Sequence

if TYPE_CHECKING:
    from ..base_run import CommonArgs, ManifestRow

# Sourced by every tool's .sh (via $SAPIA_PRELUDE) for shared task scaffolding. See core/scripts/sapia_task_prelude.sh.
PRELUDE_PATH = Path(__file__).parent.parent / "scripts" / "sapia_task_prelude.sh"


@dataclass
class SubmitCtx:
    """Everything an executor needs to launch one submission."""

    args: "CommonArgs"
    tool_name: str
    rows: "Sequence[ManifestRow]"
    manifest_base: Path
    out_dir: Path
    log_dir: Path

    @property
    def script(self) -> Path:
        return Path(self.args.script)

    def task_env(self, scheduler: str) -> dict[str, str]:
        """Env every task needs, whatever the scheduler (``SAPIA_TASK_ID`` excluded)."""
        return {
            "SAPIA_PRELUDE": str(PRELUDE_PATH),
            "SAPIA_TOOL_DIR": str(self.script.resolve().parent),
            "SAPIA_TOOL": self.tool_name,
            "SAPIA_SCHEDULER": scheduler,
        }


ExecutorFn = Callable[[SubmitCtx], None]

# name -> module under prosapia.core.executors defining ``submit``. Imported lazily
# so optional scheduler SDKs (modal) are only needed when that executor is used.
EXECUTORS = ("slurm", "modal")


def get_executor(name: str) -> ExecutorFn:
    if name not in EXECUTORS:
        raise ValueError(f"Unknown executor {name!r}. Available: {', '.join(EXECUTORS)}.")
    return importlib.import_module(f"{__name__}.{name}").submit


def write_manifest(path: Path, rows: "Sequence[ManifestRow]") -> None:
    """Manifest is tab-separated"""
    with open(path, "w") as f:
        for row in rows:
            f.write("\t".join(str(v) for v in row) + "\n")
