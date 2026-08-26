from pathlib import Path

from prosapia.core import Tool

from .collect_rfdiffusion3 import RFD3CollectArgs, _add_rfd3_collect_args, collect_rfd3
from .run_rfdiffusion3_sbatch import RFD3Args, _add_rfd3_args, build_rfd3_manifest

TOOL = Tool(
    name="rfdiffusion3",
    action="create",
    run_description="Submit a SLURM array to run RFdiffusion3 symmetric motif scaffolding.",
    collect_description="Collect RFdiffusion3 outputs into the diffusion db.",
    default_sbatch=str(Path(__file__).parent / "rfdiffusion3.sbatch"),
    default_input_column="relaxed_symm_path",
    build_fn=build_rfd3_manifest,
    add_run_args_fn=_add_rfd3_args,
    run_args_type=RFD3Args,
    collect_fn=collect_rfd3,
    add_collect_args_fn=_add_rfd3_collect_args,
    collect_args_type=RFD3CollectArgs,
)
