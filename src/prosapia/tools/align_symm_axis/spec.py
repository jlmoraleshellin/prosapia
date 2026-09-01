from pathlib import Path

from prosapia.core import Tool

from .collect_align_symm_axis import collect_align_symm_axis
from .run_align_symm_axis_sbatch import build_align_symm_axis_manifest

TOOL = Tool(
    name="align_symm_axis",
    action="update",
    description="Align symmetric assemblies onto the +Z axis.",
    default_sbatch=str(Path(__file__).parent / "align_symm_axis.sbatch"),
    default_input_column="symm_path",
    build_manifest_fn=build_align_symm_axis_manifest,
    collect_fn=collect_align_symm_axis,
)
