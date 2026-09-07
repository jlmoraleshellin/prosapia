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

from typing import Iterable

import pandas as pd

from prosapia.core import Collected, CollectCtx, CollectEach, DesignCtx


def collect_make_symmdef(ctx: CollectCtx) -> CollectEach:
    """Per-design make_symmdef collector. The framework iterates ready designs and
    stamps status/path (keyed by the tool leaf); this reads one design's one-row
    <name>.tsv. Variants are distinguished via --dir-label, matching the output dir."""

    def one(d: DesignCtx) -> Iterable[Collected]:
        tsv_path = ctx.out_dir / f"{d.name}.tsv"

        if not tsv_path.is_file():
            yield Collected(status="missing", path="")
            return

        result_df = pd.read_csv(tsv_path, sep="\t")
        if result_df.empty:
            yield Collected(status="error: empty tsv", path="")
            return

        row_data = result_df.iloc[0]
        status = str(row_data["status"])

        if status == "OK":
            symm_path = row_data["symm_path"]
            yield Collected(
                status=status,
                path="" if pd.isna(symm_path) else str(symm_path),
            )
        else:
            yield Collected(status=status, path="")

    return one
