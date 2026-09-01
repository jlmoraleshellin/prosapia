#!/usr/bin/env python3
"""
Collect USalign comparison results into the database.

Scans <run_dir>/USalign/<prefix>_results/ for per-design TSV files written
by usalign.sbatch, and merges the metrics back into the specified database.

Usage:
    sapia collect USalign outputs/RUN \
        --database db1_..._mpnn_seqs \
        --col-a boltz_path --col-b openfold3_path

    sapia collect USalign outputs/RUN \
        --database db1_..._mpnn_seqs \
        --output-prefix boltz_vs_openfold3
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Dict, cast

import pandas as pd

from prosapia.core import CollectArgs, CollectCtx, CollectResult, drop_collected

USALIGN_COLUMNS = ["TM1", "TM2", "RMSD", "ID1", "ID2", "IDali", "L1", "L2", "Lali"]


class USalignCollectArgs(CollectArgs):
    col_a: str | None
    col_b: str | None
    ref: str | None
    output_prefix: str | None


def _add_usalign_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--col-a",
        type=str,
        default=None,
        help="Database column for structure A (used to derive prefix when "
        "--output-prefix is not set).",
    )
    parser.add_argument(
        "--col-b",
        type=str,
        default=None,
        help="Database column for structure B (used to derive prefix when "
        "--output-prefix is not set).",
    )
    parser.add_argument(
        "--ref",
        type=str,
        default=None,
        help="Fixed reference structure path (used to derive prefix when "
        "--output-prefix is not set, alternative to --col-b).",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=None,
        help="Prefix used during submission. Defaults to "
        "'<col_a_stem>_vs_<col_b_stem>'.",
    )


def _resolve_prefix(args: USalignCollectArgs) -> str:
    if args.output_prefix is not None:
        return args.output_prefix
    if args.col_a is not None and args.col_b is not None:
        return f"{args.col_a.replace('_path', '')}_vs_{args.col_b.replace('_path', '')}"
    if args.col_a is not None and args.ref is not None:
        stem_b = Path(args.ref).stem.split(".")[0]
        return f"{args.col_a.replace('_path', '')}_vs_{stem_b}"
    raise ValueError("Provide --output-prefix, or --col-a with --col-b or --ref.")


def collect_usalign(ctx: CollectCtx) -> CollectResult:
    # The comparison prefix is the leaf *under* the USalign tool dir; it also
    # prefixes the columns (e.g. boltz_vs_openfold3_TM1).
    prefix = _resolve_prefix(ctx.args)
    results_dir = ctx.out_dir / prefix
    if not results_dir.is_dir():
        raise FileNotFoundError(f"Results dir not found: {results_dir}")

    status_col = f"{prefix}_status"
    sup_path_col = f"{prefix}_sup_path"

    # USalign columns are prefix-keyed, not leaf-keyed (one leaf hosts several
    # comparisons), so it can't use the plain ctx.ready done-filter -- apply the
    # shared helper with the prefix status column. Each design writes <name>.tsv.
    pending = drop_collected(ctx.ready, ctx.df, status_col, ctx.args.force)

    updates: CollectResult = {}
    n_ok = 0
    n_err = 0

    for name in pending.index:
        name = cast(str, name)
        tsv_path = results_dir / f"{name}.tsv"

        if not tsv_path.is_file():
            updates[name] = {status_col: "missing"}
            n_err += 1
            continue

        result_df = pd.read_csv(tsv_path, sep="\t")
        if result_df.empty:
            updates[name] = {status_col: "error: empty tsv"}
            n_err += 1
            continue

        row_data = result_df.iloc[0]
        status = str(row_data["status"])

        update: Dict[str, Any] = {status_col: status}

        if status == "OK":
            update[sup_path_col] = row_data["sup_path"]
            for col in USALIGN_COLUMNS:
                if col in row_data.index:
                    try:
                        update[f"{prefix}_{col}"] = float(row_data[col])
                    except (ValueError, TypeError):
                        update[f"{prefix}_{col}"] = pd.NA
            n_ok += 1
        else:
            n_err += 1

        updates[name] = update

    print(f"Done. ok={n_ok}, errors={n_err}")
    return updates
