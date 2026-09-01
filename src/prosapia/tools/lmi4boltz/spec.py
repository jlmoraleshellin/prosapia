from pathlib import Path

from prosapia.core import Tool

from .collect_boltz import collect_boltz
from .run_boltz_sbatch import _add_boltz_args, build_boltz_manifest

TOOL = Tool(
    name="boltz",
    action="update",
    description="Run Boltz structure predictions",
    default_sbatch=str(Path(__file__).parent / "boltz.sbatch"),
    default_input_column="sequence",
    build_manifest_fn=build_boltz_manifest,
    add_run_args_fn=_add_boltz_args,
    collect_fn=collect_boltz,
)
