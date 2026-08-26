from pathlib import Path

from prosapia.core import Tool

from .collect_openfold3 import collect_openfold3
from .run_openfold3_sbatch import (
    OpenFold3Args,
    _add_openfold3_args,
    build_openfold3_manifest,
)

TOOL = Tool(
    name="openfold3",
    action="update",
    run_description="Run OpenFold3 predictions on MPNN-designed sequences.",
    collect_description="Collect OpenFold3 predictions into the database.",
    default_sbatch=str(Path(__file__).parent / "openfold3.sbatch"),
    default_input_column="sequence",
    build_fn=build_openfold3_manifest,
    add_run_args_fn=_add_openfold3_args,
    run_args_type=OpenFold3Args,
    collect_fn=collect_openfold3,
)
