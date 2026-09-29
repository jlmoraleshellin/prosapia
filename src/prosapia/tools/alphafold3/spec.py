from pathlib import Path

from prosapia.core import Tool

from .collect_alphafold3 import collect_af3
from .run_alphafold3 import add_run_af3_args, build_af3_manifest

TOOL = Tool(
    name="alphafold3",
    action="update",
    description="Run AlphaFold3 structure predictions.",
    default_script=str(Path(__file__).parent / "alphafold3.sh"),
    default_input_column="proteinmpnn_sequence",
    build_manifest_fn=build_af3_manifest,
    add_run_args_fn=add_run_af3_args,
    collect_fn=collect_af3,
)
