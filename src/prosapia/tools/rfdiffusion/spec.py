from pathlib import Path

from prosapia.core import Tool

from .collect_rfdiffusion import collect_diffusion
from .run_rfdiffusion_sbatch import (
    add_run_rfdiffusion_args,
    build_rfdiff_manifest,
)

TOOL = Tool(
    name="rfdiffusion",
    action="create",
    description="Run RFdiffusion.",
    default_script=str(Path(__file__).parent / "rfdiffusion.sh"),
    default_input_column="pdb_path",
    build_manifest_fn=build_rfdiff_manifest,
    add_run_args_fn=add_run_rfdiffusion_args,
    collect_fn=collect_diffusion,
)
