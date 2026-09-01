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

from typing import cast

import pandas as pd

from prosapia.core import CollectCtx, CollectResult


def collect_align_symm_axis(ctx: CollectCtx) -> CollectResult:
    # Columns are keyed by the tool leaf (output dir name)
    max_dev_col = f"{ctx.out_dir.name}_max_dev_deg"

    updates: CollectResult = {}
    n_ok = 0
    n_err = 0

    # ctx.ready is the set of designs still to collect (already-OK rows are
    # dropped unless --force); each writes a one-row <name>.tsv.
    for name in ctx.ready.index:
        name = cast(str, name)
        tsv_path = ctx.out_dir / f"{name}.tsv"

        if not tsv_path.is_file():
            updates[name] = {
                ctx.status_col: "missing",
                ctx.path_col: "",
                max_dev_col: None,
            }
            n_err += 1
            continue

        result_df = pd.read_csv(tsv_path, sep="\t")
        if result_df.empty:
            updates[name] = {
                ctx.status_col: "error: empty tsv",
                ctx.path_col: "",
                max_dev_col: None,
            }
            n_err += 1
            continue

        row_data = result_df.iloc[0]
        status = str(row_data["status"])

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

    print(f"Done. ok={n_ok}, errors={n_err}")
    return updates
