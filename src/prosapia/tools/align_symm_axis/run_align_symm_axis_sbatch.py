#!/usr/bin/env python3
"""
Submit a SLURM array to align symmetric assemblies onto RFdiffusion's +Z axis.

Each array task runs align_symm_axis_worker.py on one design: it reads the Cn
symmetry axis from the design's Rosetta .symm file and rigidly reorients the
symmetric assembly so that axis lands on +Z at the origin -- the canonical frame
RFdiffusion expects for symmetric motif scaffolding. Use collect_align_symm_axis.py
to merge the results (aligned-PDB path + axis-quality metric) back into the db.

The .symm file is derived by name from the symmetric-PDB column, the same way
run_relax_sbatch.py does it (<stem without _symm>.symm next to it).

Usage:
    python run_align_symm_axis_sbatch.py outputs/RUN --database db \
        --input-column make_symmdef_path
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import cast

from prosapia.core import CommonArgs, ManifestCtx


class AlignSymmAxisArgs(CommonArgs):
    force: bool


def _add_align_symm_axis_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run for designs that already have status OK.",
    )


def build_align_symm_axis_manifest(
    ctx: ManifestCtx[AlignSymmAxisArgs],
) -> list[tuple[str, ...]]:
    df, args, out_dir = ctx.df, ctx.args, ctx.out_dir
    args.gpus_per_task = 0  # CPU-only tool

    col = args.input_column
    ready = df[df[col].notna() & (df[col] != "")]

    # Columns are keyed by the tool leaf (align_symm_axis[_<dir_label>]); variants
    # are distinguished via --dir-label, matching the output dir.
    status_col = f"{out_dir.name}_status"
    if args.force:
        print("Re-running align_symm_axis for all designs (including status OK).")
    elif status_col in ready.columns:
        ready = ready[ready[status_col] != "OK"]

    manifest_rows: list[tuple[str, ...]] = []
    for name in ready.index:
        name = cast(str, name)
        symm_pdb = Path(str(ready.at[name, col]))
        # Sibling .symm file (mirrors run_relax_sbatch.py's derivation).
        symm_def = symm_pdb.parent / f"{symm_pdb.stem.replace('_symm', '')}.symm"

        if not symm_pdb.exists():
            print(f"{name}: MISSING {symm_pdb} (skipping)")
            continue
        if not symm_def.exists():
            print(f"{name}: MISSING {symm_def} (skipping)")
            continue

        manifest_rows.append((name, str(symm_pdb), str(symm_def)))

    return manifest_rows
