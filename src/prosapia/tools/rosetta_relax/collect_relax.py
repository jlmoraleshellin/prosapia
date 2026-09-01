#!/usr/bin/env python3
"""
Parse Rosetta score files and append metrics to the run database.

Usage:
    sapia collect relaxed outputs/20260416_155345_grow_hairpin --database db1_...
"""

from pathlib import Path
from typing import Any, Dict, Optional, cast

import pandas as pd

from prosapia.core import CollectCtx, CollectResult

# Metrics to extract from each score file. Add/remove as needed.
METRICS = [
    "total_score",
    "complex_normalized",
    "dG_separated",
    "dG_separated/dSASAx100",
    "dSASA_int",
    "delta_unsatHbonds",
    "fa_rep",
    "fa_atr",
    "hbonds_int",
    "packstat",
    "sc_value",
    "nres_int",
]


def parse_score_file(score_file: Path) -> Optional[Dict[str, float]]:
    """
    Parse a Rosetta .sc file. Returns averaged metrics across all SCORE data
    rows, or None if the file has no data rows.

    Rosetta score files are whitespace-separated with a header like:
        SCORE: total_score complex_normalized ... description
        SCORE:  -4136.565        -12.076      ... assembled_Slyse_1_..._0001
    """
    header: Optional[list[str]] = None
    rows: list[dict[str, str]] = []

    with open(score_file) as f:
        for line in f:
            if not line.startswith("SCORE:"):
                continue
            tokens = line.split()[1:]
            if header is None:
                header = tokens
            else:
                rows.append(dict(zip(header, tokens)))

    if header is None or not rows:
        return None

    out: dict[str, float] = {}
    for metric in METRICS:
        values: list[float] = []
        for row in rows:
            if metric in row:
                try:
                    values.append(float(row[metric]))
                except ValueError:
                    pass
        if values:
            out[metric] = sum(values) / len(values)
    return out


def collect_relax(ctx: CollectCtx) -> CollectResult:
    all_score_files = sorted(ctx.out_dir.glob("*_scores.sc"))
    all_pdb_files = sorted(ctx.out_dir.glob("*_0001.pdb"))
    print(f"Found {len(all_score_files)} score files, {len(all_pdb_files)} PDB files")

    score_by_name: Dict[str, Path] = {}
    pdb_by_name: Dict[str, Path] = {}
    # ctx.ready already drops already-OK rows (unless --force) and NA-input rows.
    candidate_names = [cast(str, name) for name in ctx.ready.index]

    for name in candidate_names:
        for f in all_score_files:
            if name in f.name:
                score_by_name[name] = f
                break
        for f in all_pdb_files:
            if name in f.name:
                pdb_by_name[name] = f

    updates: CollectResult = {}
    for name in candidate_names:
        if name not in score_by_name:
            print(f"{name}: no score file")
            updates[name] = {ctx.status_col: "missing"}
            continue

        metrics = parse_score_file(score_by_name[name])
        if metrics is None:
            print(f"{name}: empty score file")
            updates[name] = {ctx.status_col: "empty"}
            continue

        relaxed_path = str(pdb_by_name[name]) if name in pdb_by_name else pd.NA

        update: Dict[str, Any] = {
            f"{ctx.out_dir.name}_{k}": v for k, v in metrics.items()
        }
        update[ctx.status_col] = "OK"
        update[ctx.path_col] = relaxed_path
        if not relaxed_path:
            update[ctx.status_col] = "OK_no_pdb"
            print(f"{name}: scores parsed but no relaxed PDB found")

        updates[name] = update
        print(
            f"{name}: dG_sep={metrics.get('dG_separated', float('nan')):7.2f}  "
            f"fa_rep={metrics.get('fa_rep', float('nan')):8.2f}  "
            f"total={metrics.get('total_score', float('nan')):9.2f}"
        )

    return updates
