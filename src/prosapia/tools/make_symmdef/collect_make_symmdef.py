#!/usr/bin/env python3
"""
Collect make_symmdef results into the database.

Scans <run_dir>/<database>/make_symmdef/ for the per-design TSV files written
by make_symmdef.sbatch, and merges the symm status + path back into the
specified database as <prefix>_status / <prefix>_path columns.

Usage:
    python collect_make_symmdef.py outputs/RUN \
        --database db1_..._assembled
"""

import pandas as pd

from prosapia.core import CollectCtx, CollectResult


def collect_make_symmdef(ctx: CollectCtx) -> CollectResult:
    df, args, out_dir = ctx.df, ctx.args, ctx.out_dir

    # Columns are keyed by the tool leaf (make_symmdef[_<dir_label>]); variants
    # are distinguished via --dir-label, matching the output dir.
    prefix = out_dir.name
    status_col = f"{prefix}_status"
    path_col = f"{prefix}_path"

    tsvs = sorted(ctx.out_dir.glob("*.tsv"))
    print(f"Found {len(tsvs)} result file(s) in {ctx.out_dir}")

    updates: CollectResult = {}
    n_ok = 0
    n_err = 0
    n_skipped = 0

    for tsv_path in tsvs:
        result_df = pd.read_csv(tsv_path, sep="\t")
        if result_df.empty:
            n_err += 1
            continue

        row_data = result_df.iloc[0]
        name = str(row_data["name"])
        status = str(row_data["status"])

        if (
            not args.force
            and status_col in df.columns
            and name in df.index
            and not pd.isna(df.at[name, status_col])
            and df.at[name, status_col] == "OK"
        ):
            n_skipped += 1
            continue

        if status == "OK":
            symm_path = row_data["symm_path"]
            updates[name] = {
                status_col: status,
                path_col: "" if pd.isna(symm_path) else str(symm_path),
            }
            n_ok += 1
        else:
            updates[name] = {status_col: status, path_col: ""}
            n_err += 1

    skipped_msg = f", skipped={n_skipped}" if n_skipped else ""
    print(f"Done. ok={n_ok}, errors={n_err}{skipped_msg}")
    return updates
