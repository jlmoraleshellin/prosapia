from pathlib import Path

from .collect_proteinmpnn import collect_mpnn
from .run_proteinmpnn_sbatch import (
    add_proteinmpnn_args,
    build_proteinmpnn_manifest,
)

from prosapia.core import Tool

TOOL = Tool(
    name="mpnn_seqs",
    action="create",
    description="Run ProteinMPNN on a set of input PDBs.",
    default_sbatch=str(Path(__file__).parent / "run_proteinmpnn.sbatch"),
    default_input_column="diffused_path",
    build_manifest_fn=build_proteinmpnn_manifest,
    add_run_args_fn=add_proteinmpnn_args,
    collect_fn=collect_mpnn,
)
