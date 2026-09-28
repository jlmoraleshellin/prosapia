#!/usr/bin/env python3
"""
Collect PyRosetta scoring results into the table.

Reads the per-design <name>.tsv files written by pyrosetta_worker.py under
<run_dir>/<table>/<leaf>/ and merges them back as <leaf>_* columns: the scored
(relaxed) PDB as <leaf>_path, and every metric the worker recorded (total_score,
score_per_res, the weighted score terms, sasa, packstat, interface metrics, ...).

Usage:
    sapia collect pyrosetta outputs/RUN --table table1
"""

from typing import Any, Iterable

import pandas as pd

from prosapia.core import Collected, CollectCtx, CollectEach, DesignCtx

# Columns of the worker's TSV that are bookkeeping, not metrics.
_META_COLUMNS = {"name", "status", "scored_path"}


def _value(v: Any) -> Any:
    """Metrics as floats where they parse; anything else (e.g. dssp) as-is."""
    if pd.isna(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def collect_pyrosetta(ctx: CollectCtx) -> CollectEach:
    """Per-design PyRosetta collector. The worker writes a variable set of metric
    columns (the score terms depend on --scorefxn, interface metrics on
    --interface), so every non-bookkeeping column is passed through as bare data
    and the driver leaf-prefixes it."""

    def one(d: DesignCtx) -> Iterable[Collected]:
        tsv_path = ctx.out_dir / f"{d.name}.tsv"

        if not tsv_path.is_file():
            yield Collected(status="missing", path="")
            return

        result_df = pd.read_csv(tsv_path, sep="\t", keep_default_na=True)
        if result_df.empty:
            yield Collected(status="error: empty tsv", path="")
            return

        row = result_df.iloc[0]
        status = str(row["status"])
        if status != "OK":
            yield Collected(status=status, path="")
            return

        # Rebuild the path from out_dir rather than trusting the worker's absolute
        # one, so it is stored run-relative like every other tool's <leaf>_path.
        scored = ctx.out_dir / f"{d.name}.pdb"
        data = {
            str(col): _value(row[col])
            for col in result_df.columns
            if col not in _META_COLUMNS
        }
        yield Collected(
            status=status,
            path=str(scored) if scored.is_file() else "",
            data=data,
        )

    return one
