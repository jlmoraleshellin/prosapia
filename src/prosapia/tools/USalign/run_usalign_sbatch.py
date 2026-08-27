#!/usr/bin/env python3
"""
Submit a SLURM array to compare two predicted structures per design using USalign.

Both structures are converted to PDB (via gemmi) here at manifest-build time and
cached under <run_dir>/.cif_to_pdb/; each array task then just runs USalign and
writes per-design metrics to a TSV file. Use ``sapia collect USalign`` to merge
results back into the database.

--col-b is resolved per design by lineage (the row's own value if set, else the
nearest ancestor db's value), so a child db's structure can be compared against
its parent's (e.g. boltz_path vs the parent's diffused_path).

Usage:
    sapia run USalign outputs/20260420_123035_grow_hairpin \
        --database mpnn_seqs_db \
        --col-a boltz_path --col-b openfold3_path

    # Compare each child's boltz_path against its parent's diffused_path:
    sapia run USalign outputs/20260420_123035_grow_hairpin \
        --database db2_child \
        --col-a boltz_path --col-b diffused_path

    sapia run USalign outputs/20260420_123035_grow_hairpin \
        --database mpnn_seqs_db \
        --col-a boltz_path --col-b openfold3_path \
        --output-prefix boltz_vs_openfold3
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import cast

import pandas as pd

from prosapia.core import CommonArgs, ManifestCtx, ensure_pdb


class USalignArgs(CommonArgs):
    col_a: str
    col_b: str | None
    ref: str | None
    output_prefix: str | None
    force: bool


def _add_usalign_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--col-a",
        type=str,
        required=True,
        help="Database column containing the path to structure A.",
    )
    parser.add_argument(
        "--col-b",
        type=str,
        default=None,
        help="Column containing the path to structure B. Resolved per design by "
        "lineage: the row's own value if set, otherwise the nearest ancestor db's "
        "value (matched by parent), so e.g. a child's boltz_path can be compared "
        "against its parent's diffused_path.",
    )
    parser.add_argument(
        "--ref",
        type=str,
        default=None,
        help="Fixed reference structure path to use for all comparisons "
        "(alternative to --col-b).",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=None,
        help="Prefix for output columns and subdirectory. Defaults to "
        "'<col_a_stem>_vs_<col_b_stem>' (e.g. 'boltz_vs_openfold3').",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run USalign for designs that already have status OK.",
    )


def _resolve_prefix(args: USalignArgs) -> str:
    if args.output_prefix is not None:
        return args.output_prefix
    stem_a = args.col_a.replace("_path", "")
    if args.ref is not None:
        stem_b = Path(args.ref).stem.split(".")[0]
    else:
        assert args.col_b is not None
        stem_b = args.col_b.replace("_path", "")
    return f"{stem_a}_vs_{stem_b}"


def build_usalign_manifest(ctx: ManifestCtx[USalignArgs]) -> list[tuple[str, ...]]:
    df, args = ctx.df, ctx.args
    args.gpus_per_task = 0

    if args.col_b is None and args.ref is None:
        raise ValueError("Either --col-b or --ref must be provided.")
    if args.col_b is not None and args.ref is not None:
        raise ValueError("Cannot use both --col-b and --ref.")

    col_a = args.col_a
    prefix = _resolve_prefix(args)

    ready = df[df[col_a].notna() & (df[col_a] != "")]

    status_col = f"{prefix}_status"
    if args.force:
        print("Re-running USalign for all designs (including those with status OK).")
    elif status_col in ready.columns:
        ready = ready[ready[status_col] != "OK"]

    ref_path = str(Path(args.ref).resolve()) if args.ref else None
    col_b_label = "ref" if args.ref else cast(str, args.col_b)

    manifest_rows: list[tuple[str, ...]] = []
    for name in ready.index:
        name = cast(str, name)
        src_a = Path(str(ready.at[name, col_a]))
        if ref_path:
            src_b = Path(ref_path)
        else:
            val = ctx.lookup(name, cast(str, args.col_b))
            if pd.isna(val) or str(val) == "":
                continue  # no col_b structure on this row or its ancestors
            src_b = Path(str(val))
        # Stage CIF->PDB up front (cached under run_dir/.cif_to_pdb). A missing
        # input is passed through raw so the sbatch records it as an error.
        pdb_a = ensure_pdb(src_a, args.run_dir) if src_a.exists() else src_a
        pdb_b = ensure_pdb(src_b, args.run_dir) if src_b.exists() else src_b
        manifest_rows.append((name, str(pdb_a), str(pdb_b), col_a, col_b_label, prefix))

    return manifest_rows
