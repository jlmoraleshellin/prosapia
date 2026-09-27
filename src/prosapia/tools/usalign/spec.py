from pathlib import Path

from prosapia.core import Tool

from .collect_usalign import add_collect_usalign_args, collect_usalign
from .run_usalign_sbatch import (
    add_run_usalign_args,
    build_usalign_manifest,
)

TOOL = Tool(
    name="usalign",
    action="update",
    description="Compare structures using USalign.",
    default_sbatch=str(Path(__file__).parent / "usalign.sbatch"),
    default_input_column="not applicable",
    build_manifest_fn=build_usalign_manifest,
    add_run_args_fn=add_run_usalign_args,
    collect_fn=collect_usalign,
    add_collect_args_fn=add_collect_usalign_args,
)
