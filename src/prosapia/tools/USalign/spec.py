from pathlib import Path

from prosapia.core import Tool

from .collect_usalign import _add_usalign_args, collect_usalign
from .run_usalign_sbatch import (
    _add_usalign_args as _add_usalign_run_args,
    build_usalign_manifest,
)

TOOL = Tool(
    name="USalign",
    action="update",
    description="Compare structures using USalign.",
    default_sbatch=str(Path(__file__).parent / "usalign.sbatch"),
    default_input_column="not applicable",
    build_manifest_fn=build_usalign_manifest,
    add_run_args_fn=_add_usalign_run_args,
    collect_fn=collect_usalign,
    add_collect_args_fn=_add_usalign_args,
)
