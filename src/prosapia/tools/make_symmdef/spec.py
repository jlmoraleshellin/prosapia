from pathlib import Path

from prosapia.core import Tool

from .collect_make_symmdef import collect_make_symmdef
from .run_make_symmdef_sbatch import build_make_symmdef_manifest

TOOL = Tool(
    name="symmdef",
    action="update",
    description="Make symmetry definition files.",
    default_sbatch=str(Path(__file__).parent / "symmdef.sbatch"),
    default_input_column="assembled_path",
    build_manifest_fn=build_make_symmdef_manifest,
    collect_fn=collect_make_symmdef,
)
