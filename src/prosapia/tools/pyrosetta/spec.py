from pathlib import Path

from prosapia.core import Tool

from .collect_pyrosetta import collect_pyrosetta
from .run_pyrosetta import add_run_pyrosetta_args, build_pyrosetta_manifest

TOOL = Tool(
    name="pyrosetta",
    action="update",
    description="Score structures with PyRosetta (optional FastRelax) for energy metrics.",
    default_script=str(Path(__file__).parent / "pyrosetta.sh"),
    default_input_column="boltz_path",
    build_manifest_fn=build_pyrosetta_manifest,
    add_run_args_fn=add_run_pyrosetta_args,
    collect_fn=collect_pyrosetta,
)
