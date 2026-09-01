#!/usr/bin/env python3
"""
Collect make_symmdef results into the database.

Scans <run_dir>/<database>/make_symmdef/ for the per-design TSV files written
by make_symmdef.sbatch, and merges the symm status + path back into the
specified database as <prefix>_status / <prefix>_path columns.

Usage:
    sapia collect make_symmdef outputs/RUN \
        --database db1_..._assembled
"""

from typing import cast

import pandas as pd

from prosapia.core import CollectCtx, CollectResult


def collect_make_symmdef(ctx: CollectCtx) -> CollectResult:
    # Columns are keyed by the tool leaf (make_symmdef[_<dir_label>]); variants
    # are distinguished via --dir-label, matching the output dir.
    updates: CollectResult = {}
    n_ok = 0
    n_err = 0

    # ctx.ready is the set of designs still to collect (already-OK rows are
    # dropped unless --force); each writes a one-row <name>.tsv.
    for name in ctx.ready.index:
        name = cast(str, name)
        tsv_path = ctx.out_dir / f"{name}.tsv"

        if not tsv_path.is_file():
            updates[name] = {ctx.status_col: "missing", ctx.path_col: ""}
            n_err += 1
            continue

        result_df = pd.read_csv(tsv_path, sep="\t")
        if result_df.empty:
            updates[name] = {ctx.status_col: "error: empty tsv", ctx.path_col: ""}
            n_err += 1
            continue

        row_data = result_df.iloc[0]
        status = str(row_data["status"])

        if status == "OK":
            symm_path = row_data["symm_path"]
            updates[name] = {
                ctx.status_col: status,
                ctx.path_col: "" if pd.isna(symm_path) else str(symm_path),
            }
            n_ok += 1
        else:
            updates[name] = {ctx.status_col: status, ctx.path_col: ""}
            n_err += 1

    print(f"Done. ok={n_ok}, errors={n_err}")
    return updates
