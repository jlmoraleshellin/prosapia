from pathlib import Path

from prosapia.core import Tool

from .collect_make_symmdef import collect_make_symmdef
from .run_make_symmdef import build_make_symmdef_manifest, add_make_symmdef_args

TOOL = Tool(
    name="make_symmdef",
    action="update",
    description="Make symmetry definition files.",
    default_script=str(Path(__file__).parent / "make_symmdef.sh"),
    default_input_column="pdb_path",
    build_manifest_fn=build_make_symmdef_manifest,
    add_run_args_fn=add_make_symmdef_args,
    collect_fn=collect_make_symmdef,
)
