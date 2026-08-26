from pathlib import Path

from prosapia.core import Tool

from .collect_boltz import collect_boltz
from .run_boltz_sbatch import BoltzArgs, _add_boltz_args, build_boltz_manifest

TOOL = Tool(
    name="boltz",
    action="update",
    run_description="Submit a SLURM array to predict sequences listed in the DB.",
    collect_description="Collect boltz predictions into the database.",
    default_sbatch=str(Path(__file__).parent / "boltz.sbatch"),
    default_input_column="sequence",
    build_fn=build_boltz_manifest,
    add_run_args_fn=_add_boltz_args,
    run_args_type=BoltzArgs,
    collect_fn=collect_boltz,
)
