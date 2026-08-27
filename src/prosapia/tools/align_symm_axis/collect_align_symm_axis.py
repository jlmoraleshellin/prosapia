#!/usr/bin/env python3
"""
Collect align_symm_axis results into the database.

Scans <run_dir>/<database>/align_symm_axis/ for the per-design TSV files written
by align_symm_axis.sbatch, and merges the alignment status, aligned-PDB path and
axis-quality metric back into the database as <prefix>_status / <prefix>_path /
<prefix>_max_dev_deg columns.

Usage:
    sapia collect align_symm_axis outputs/RUN --database db
"""

import pandas as pd

from prosapia.core import CollectCtx, CollectResult


def collect_align_symm_axis(ctx: CollectCtx) -> CollectResult:
    df, args, out_dir = ctx.df, ctx.args, ctx.out_dir

    # Columns are keyed by the tool leaf (output dir name)
    prefix = out_dir.name
    status_col = f"{prefix}_status"
    path_col = f"{prefix}_path"
    max_dev_col = f"{prefix}_max_dev_deg"

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
            aligned_path = row_data["aligned_path"]
            max_dev = row_data["max_dev_deg"]
            updates[name] = {
                status_col: status,
                path_col: "" if pd.isna(aligned_path) else str(aligned_path),
                max_dev_col: None if pd.isna(max_dev) else float(max_dev),
            }
            n_ok += 1
        else:
            updates[name] = {status_col: status, path_col: "", max_dev_col: None}
            n_err += 1

    skipped_msg = f", skipped={n_skipped}" if n_skipped else ""
    print(f"Done. ok={n_ok}, errors={n_err}{skipped_msg}")
    return updates
