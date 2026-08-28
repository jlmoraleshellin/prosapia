from pathlib import Path

from prosapia.core import Tool

from .collect_make_symmdef import collect_make_symmdef
from .run_make_symmdef_sbatch import (
    MakeSymmdefArgs,
    _add_make_symmdef_args,
    build_make_symmdef_manifest,
)

TOOL = Tool(
    name="symmdef",
    action="update",
    run_description="Submit a SLURM array to make symmetry definitions.",
    collect_description="Collect symmdef files into the database.",
    default_sbatch=str(Path(__file__).parent / "symmdef.sbatch"),
    default_input_column="assembled_path",
    build_fn=build_make_symmdef_manifest,
    add_run_args_fn=_add_make_symmdef_args,
    run_args_type=MakeSymmdefArgs,
    collect_fn=collect_make_symmdef,
)
