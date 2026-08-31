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
    # Columns are keyed by the tool leaf (output dir name)
    max_dev_col = f"{ctx.out_dir.name}_max_dev_deg"

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
            not ctx.args.force
            and ctx.status_col in ctx.df.columns
            and name in ctx.df.index
            and not pd.isna(ctx.df.at[name, ctx.status_col])
            and ctx.df.at[name, ctx.status_col] == "OK"
        ):
            n_skipped += 1
            continue

        if status == "OK":
            aligned_path = row_data["aligned_path"]
            max_dev = row_data["max_dev_deg"]
            updates[name] = {
                ctx.status_col: status,
                ctx.path_col: "" if pd.isna(aligned_path) else str(aligned_path),
                max_dev_col: None if pd.isna(max_dev) else float(max_dev),
            }
            n_ok += 1
        else:
            updates[name] = {
                ctx.status_col: status,
                ctx.path_col: "",
                max_dev_col: None,
            }
            n_err += 1

    skipped_msg = f", skipped={n_skipped}" if n_skipped else ""
    print(f"Done. ok={n_ok}, errors={n_err}{skipped_msg}")
    return updates
