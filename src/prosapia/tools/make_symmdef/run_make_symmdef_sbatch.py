#!/usr/bin/env python3
"""
Submit a SLURM array to make symmetry definitions for assembled designs.

Each array task runs Rosetta's make_symmdef_file.pl on one input PDB (read from
--input-column) and writes a per-design TSV. Use collect_make_symmdef.py to
merge the results (symm status + path) back into the database.

Usage:
    sapia run make_symmdef outputs/20260416_155345_grow_hairpin \
        --database db1_..._assembled \
        --input-column assembled_path
"""

from pathlib import Path
from typing import cast

from prosapia.core import (
    CommonArgs,
    ManifestCtx,
)
from prosapia.utils import ensure_pdb


def build_make_symmdef_manifest(
    ctx: ManifestCtx[CommonArgs],
) -> list[tuple[str, ...]]:
    ctx.args.gpus_per_task = 0  # CPU-only tool

    ready = ctx.ready

    manifest_rows: list[tuple[str, ...]] = []
    for name in ready.index:
        name = cast(str, name)
        src = Path(str(ready.at[name, ctx.args.input_column]))
        # Convert CIF->PDB up front (cached under run_dir/.cif_to_pdb). A missing
        # input is passed through raw so the sbatch records it as an error.
        input_pdb = ensure_pdb(src, ctx.args.run_dir) if src.exists() else src
        manifest_rows.append((name, str(input_pdb)))

    return manifest_rows
