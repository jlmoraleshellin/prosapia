from pathlib import Path

from prosapia.core import Tool

from .collect_rfdiffusion import (
    DiffusionCollectArgs,
    _add_diffusion_args,
    collect_diffusion,
)
from .run_rfdiffusion_sbatch import (
    RFDiffArgs,
    add_extra_args_rfdiffusion,
    build_rfdiff_manifest,
)

TOOL = Tool(
    name="diffused",
    action="create",
    run_description="Submit a SLURM array to run RFdiffusion.",
    collect_description="Collect RFdiffusion partial-diffusion outputs into the diffusion db.",
    # NOTE: preserves the current __main__ default; see migration flag re: partialdiffusion.sbatch
    default_sbatch=str(Path(__file__).parent / "partialdiffusion.sbatch"),
    default_input_column="relaxed_symm_path",
    build_fn=build_rfdiff_manifest,
    add_run_args_fn=add_extra_args_rfdiffusion,
    run_args_type=RFDiffArgs,
    collect_fn=collect_diffusion,
    add_collect_args_fn=_add_diffusion_args,
    collect_args_type=DiffusionCollectArgs,
)
