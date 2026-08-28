from pathlib import Path

from prosapia.core import Tool

from .collect_usalign import USalignCollectArgs, _add_usalign_args, collect_usalign
from .run_usalign_sbatch import (
    USalignArgs,
    _add_usalign_args as _add_usalign_run_args,
    build_usalign_manifest,
)

TOOL = Tool(
    name="USalign",
    action="update",
    run_description="Submit a SLURM array to compare structures using USalign.",
    collect_description="Collect USalign comparison results into the database.",
    default_sbatch=str(Path(__file__).parent / "usalign.sbatch"),
    default_input_column="not applicable",
    build_manifest_fn=build_usalign_manifest,
    add_run_args_fn=_add_usalign_run_args,
    run_args_type=USalignArgs,
    collect_fn=collect_usalign,
    add_collect_args_fn=_add_usalign_args,
    collect_args_type=USalignCollectArgs,
)
