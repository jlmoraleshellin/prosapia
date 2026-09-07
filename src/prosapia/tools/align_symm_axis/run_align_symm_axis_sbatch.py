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
    sapia run align_symm_axis outputs/RUN --database db \
        --input-column make_symmdef_path
"""

from pathlib import Path
from typing import cast

from prosapia.core import CommonArgs, ManifestCtx


def build_align_symm_axis_manifest(
    ctx: ManifestCtx[CommonArgs],
) -> list[tuple[str, ...]]:
    ctx.args.gpus_per_task = 0  # CPU-only tool

    ready = ctx.ready

    manifest_rows: list[tuple[str, ...]] = []
    for name in ready.index:
        name = cast(str, name)
        symm_pdb = Path(str(ready.at[name, ctx.args.input_column]))
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
