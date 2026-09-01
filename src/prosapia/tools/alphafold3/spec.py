from pathlib import Path

from prosapia.core import Tool

from .collect_alphafold3 import collect_af3
from .run_alphafold3_sbatch import AlphaFold3Args, _add_af3_args, build_af3_manifest

TOOL = Tool(
    name="alphafold3",
    action="update",
    description="Run AlphaFold3 structure predictions.",
    default_sbatch=str(Path(__file__).parent / "alphafold3.sbatch"),
    default_input_column="sequence",
    build_manifest_fn=build_af3_manifest,
    add_run_args_fn=_add_af3_args,
    run_args_type=AlphaFold3Args,
    collect_fn=collect_af3,
)
