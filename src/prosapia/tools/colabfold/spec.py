from pathlib import Path

from prosapia.core import Tool

from .collect_colabfold import collect_colabfold
from .run_colabfold_sbatch import (
    ColabFoldArgs,
    _add_colabfold_args,
    build_colabfold_manifest,
)

TOOL = Tool(
    name="colabfold",
    action="update",
    description="Run ColabFold structure predictions.",
    default_sbatch=str(Path(__file__).parent / "colabfold.sbatch"),
    default_input_column="sequence",
    build_manifest_fn=build_colabfold_manifest,
    add_run_args_fn=_add_colabfold_args,
    run_args_type=ColabFoldArgs,
    collect_fn=collect_colabfold,
)
