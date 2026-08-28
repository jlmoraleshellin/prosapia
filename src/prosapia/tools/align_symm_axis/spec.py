from pathlib import Path

from prosapia.core import Tool

from .collect_align_symm_axis import collect_align_symm_axis
from .run_align_symm_axis_sbatch import (
    AlignSymmAxisArgs,
    _add_align_symm_axis_args,
    build_align_symm_axis_manifest,
)

TOOL = Tool(
    name="align_symm_axis",
    action="update",
    run_description="Submit a SLURM array to align symmetric assemblies onto +Z.",
    collect_description="Collect align_symm_axis results into the database.",
    default_sbatch=str(Path(__file__).parent / "align_symm_axis.sbatch"),
    default_input_column="symm_path",
    build_manifest_fn=build_align_symm_axis_manifest,
    add_run_args_fn=_add_align_symm_axis_args,
    run_args_type=AlignSymmAxisArgs,
    collect_fn=collect_align_symm_axis,
)
