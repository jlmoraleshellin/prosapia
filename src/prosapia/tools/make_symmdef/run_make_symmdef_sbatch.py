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

from argparse import ArgumentParser
from pathlib import Path
from typing import cast

from prosapia.core import (
    CommonArgs,
    ManifestCtx,
    ensure_pdb,
)


class MakeSymmdefArgs(CommonArgs):
    force: bool


def _add_make_symmdef_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run for designs that already have status OK.",
    )


def build_make_symmdef_manifest(
    ctx: ManifestCtx[MakeSymmdefArgs],
) -> list[tuple[str, ...]]:
    df, args, out_dir = ctx.df, ctx.args, ctx.out_dir
    args.gpus_per_task = 0  # CPU-only tool

    col = args.input_column
    ready = df[df[col].notna() & (df[col] != "")]

    # Columns are keyed by the tool leaf (make_symmdef[_<dir_label>]); variants
    # are distinguished via --dir-label, matching the output dir.
    status_col = f"{out_dir.name}_status"
    if args.force:
        print("Re-running make_symmdef for all designs (including status OK).")
    elif status_col in ready.columns:
        ready = ready[ready[status_col] != "OK"]

    manifest_rows: list[tuple[str, ...]] = []
    for name in ready.index:
        name = cast(str, name)
        src = Path(str(ready.at[name, col]))
        # Convert CIF->PDB up front (cached under run_dir/.cif_to_pdb). A missing
        # input is passed through raw so the sbatch records it as an error.
        input_pdb = ensure_pdb(src, args.run_dir) if src.exists() else src
        manifest_rows.append((name, str(input_pdb)))

    return manifest_rows
