from pathlib import Path

from prosapia.core import Tool

from .collect_relax import collect_relax
from .run_relax_sbatch import build_relax_manifest

TOOL = Tool(
    name="relaxed",
    action="update",
    run_description="Submit a SLURM array to relax designs listed in the DB.",
    collect_description="Collect Rosetta relax score files into the database.",
    # NOTE: preserves the current __main__ default; see migration flag re: relax_array.sbatch
    default_sbatch=str(Path(__file__).parent / "relax_array.sbatch"),
    default_input_column="symm_path",
    build_manifest_fn=build_relax_manifest,
    collect_fn=collect_relax,
)
