#!/usr/bin/env python3
"""
Collect ColabFold prediction results into the database.

ColabFold dumps all outputs flat into each task directory.  This script scans
``task_*/`` for score files, extracts the design name from each filename, and
picks the rank-1 model per design.

Output structure expected (per task directory):

    <colabfold_dir>/task_<i>/
        <design>_scores_rank_001_*.json
        <design>_relaxed_rank_001_*.pdb   (or _unrelaxed_ if no relaxation)
        <design>_scores_rank_002_*.json
        ...

Usage:
    sapia collect colabfold outputs/RUN --database db1_..._mpnn_seqs
    sapia collect colabfold outputs/RUN --database db1_..._mpnn_seqs --force
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, cast

import numpy as np
import pandas as pd

from prosapia.core import CollectCtx, CollectResult


def _build_design_file_map(
    colabfold_dir: Path,
) -> dict[str, tuple[Path, Path]]:
    """Scan task directories and map each design to its rank-1 output files.

    Returns {design_name: (scores_json, model_pdb)}.
    """
    design_files: dict[str, tuple[Path, Path]] = {}
    score_re = re.compile(r"^(.+)_scores_rank_001_")

    for task_dir in sorted(colabfold_dir.iterdir()):
        if not task_dir.is_dir() or not task_dir.name.startswith("task_"):
            continue
        for scores_file in task_dir.glob("*_scores_rank_001_*.json"):
            m = score_re.match(scores_file.name)
            if m is None:
                continue
            design_name = m.group(1)

            relaxed = list(task_dir.glob(f"{design_name}_relaxed_rank_001_*.pdb"))
            if relaxed:
                model_path = sorted(relaxed)[0]
            else:
                unrelaxed = list(
                    task_dir.glob(f"{design_name}_unrelaxed_rank_001_*.pdb")
                )
                if not unrelaxed:
                    continue
                model_path = sorted(unrelaxed)[0]

            design_files[design_name] = (scores_file, model_path)

    return design_files


def load_metrics(prefix: str, json_path: Path) -> Dict[str, Any]:
    with open(json_path) as f:
        data = json.load(f)
    plddt = data.get("plddt")
    avg_plddt = float(np.mean(plddt)) if plddt else pd.NA
    return {
        f"{prefix}_{metric}": value
        for metric, value in [
            ("avg_plddt", avg_plddt),
            ("ptm", data.get("ptm", pd.NA)),
            ("iptm", data.get("iptm", pd.NA)),
            ("max_pae", data.get("max_pae", pd.NA)),
        ]
    }


def collect_colabfold(ctx: CollectCtx) -> CollectResult:
    df, args, cf_dir = ctx.df, ctx.args, ctx.out_dir

    prefix = cf_dir.name
    path_col = f"{prefix}_path"
    status_col = f"{prefix}_status"
    metrics_cols: List[str] = [
        f"{prefix}_{m}" for m in ("avg_plddt", "ptm", "iptm", "max_pae")
    ]

    if df.empty:
        raise RuntimeError(
            f"Database {args.database!r} is empty or missing in {args.run_dir}."
        )

    ready = df[
        df["sequence"].notna()
        & (df["sequence"] != "")
        & ~df.index.astype(str).str.endswith("_f0")
    ]

    if not args.force and path_col in df.columns:
        existing = df.loc[ready.index, path_col]
        already_done = ready.index[existing.notna() & (existing != "")]
        if len(already_done) > 0:
            print(
                f"Skipping {len(already_done)} already-collected design(s) "
                f"(use --force to re-collect)"
            )
            ready = ready.drop(already_done)

    design_files = _build_design_file_map(cf_dir)

    updates: CollectResult = {}
    n_filled = 0
    n_missing = 0
    for design_name in ready.index:
        design_name = cast(str, design_name)
        files = design_files.get(design_name)

        if files is None:
            row: Dict[str, Any] = {status_col: "missing", path_col: pd.NA}
            row.update({k: pd.NA for k in metrics_cols})
            updates[design_name] = row
            n_missing += 1
            continue

        scores_path, model_path = files
        try:
            metrics = load_metrics(prefix, scores_path)
        except (OSError, json.JSONDecodeError) as exc:
            row = {
                status_col: f"error: {exc.__class__.__name__}: {exc}",
                path_col: pd.NA,
            }
            row.update({k: pd.NA for k in metrics_cols})
            updates[design_name] = row
            n_missing += 1
            continue

        row = {status_col: "OK", path_col: str(model_path)}
        row.update(metrics)
        updates[design_name] = row
        n_filled += 1

    print(
        f"Done. filled={n_filled}, missing={n_missing}, total_considered={len(ready)}"
    )
    return updates
