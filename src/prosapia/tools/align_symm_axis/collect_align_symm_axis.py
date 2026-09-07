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

from typing import Iterable

import pandas as pd

from prosapia.core import Collected, CollectCtx, CollectEach, DesignCtx


def collect_align_symm_axis(ctx: CollectCtx) -> CollectEach:
    """Per-design align_symm_axis collector. The framework iterates ready designs and
    stamps status/path (keyed by the tool leaf); this reads one design's one-row
    <name>.tsv and adds the axis-quality metric column."""
    # The axis-quality column is keyed by the tool leaf (output dir name).
    max_dev_col = f"{ctx.out_dir.name}_max_dev_deg"

    def one(d: DesignCtx) -> Iterable[Collected]:
        tsv_path = ctx.out_dir / f"{d.name}.tsv"

        if not tsv_path.is_file():
            yield Collected(status="missing", path="", data={max_dev_col: None})
            return

        result_df = pd.read_csv(tsv_path, sep="\t")
        if result_df.empty:
            yield Collected(
                status="error: empty tsv", path="", data={max_dev_col: None}
            )
            return

        row_data = result_df.iloc[0]
        status = str(row_data["status"])

        if status == "OK":
            aligned_path = row_data["aligned_path"]
            max_dev = row_data["max_dev_deg"]
            yield Collected(
                status=status,
                path="" if pd.isna(aligned_path) else str(aligned_path),
                data={max_dev_col: None if pd.isna(max_dev) else float(max_dev)},
            )
        else:
            yield Collected(status=status, path="", data={max_dev_col: None})

    return one
