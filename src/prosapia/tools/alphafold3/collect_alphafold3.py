#!/usr/bin/env python3
"""
Collect AlphaFold3 prediction results into the database.

Scans results_shard directories for prediction outputs and writes metrics +
model path into the database.  AF3 already selects the best-ranked model and
places it directly in the design directory.

Output structure expected:

    <af3_dir>/results_shard_<i>/<design_name>/
        <design_name>_model.cif
        <design_name>_summary_confidences.json
        <design_name>_confidences.json
        <design_name>_data.json
        <design_name>_ranking_scores.csv

Usage:
    python collect_alphafold3.py outputs/20260420_123035_grow_hairpin
    python collect_alphafold3.py outputs/20260420_123035_grow_hairpin --force
"""

import json
from pathlib import Path
from typing import Any, Dict, List, cast

import pandas as pd

from prosapia.core import (
    CollectCtx,
    CollectResult,
)

AF3_JSON_KEYS: List[str] = [
    "ranking_score",
    "ptm",
    "iptm",
    "fraction_disordered",
    "has_clash",
]


def _get_af3_metrics(prefix: str) -> List[str]:
    return [f"{prefix}_{k}" for k in AF3_JSON_KEYS]


def find_prediction_files(
    design_dir: Path,
) -> tuple[Path | None, Path | None]:
    """Locate the AF3 output files for a design.

    AF3 places the best-ranked model directly in ``<name>/<name>_model.cif``.
    Returns (summary_json, model_cif), or (None, None).
    """
    name = design_dir.name
    summary = design_dir / f"{name}_summary_confidences.json"
    cif = design_dir / f"{name}_model.cif"
    if not summary.exists() or not cif.exists():
        return None, None
    return summary, cif


def load_metrics(prefix: str, json_path: Path) -> Dict[str, Any]:
    with open(json_path) as f:
        data = json.load(f)
    return {f"{prefix}_{k}": data.get(k, pd.NA) for k in AF3_JSON_KEYS}


def collect_af3(ctx: CollectCtx) -> CollectResult:
    df, args, af3_dir = ctx.df, ctx.args, ctx.out_dir

    path_col = f"{af3_dir.name}_path"
    status_col = f"{af3_dir.name}_status"

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

    design_dirs: dict[str, Path] = {}
    for shard_dir in sorted(af3_dir.glob("results_shard_*")):
        if not shard_dir.is_dir():
            continue
        for design_dir in shard_dir.iterdir():
            if design_dir.is_dir():
                design_dirs[design_dir.name] = design_dir

    updates: CollectResult = {}
    n_filled = 0
    n_missing = 0
    for design_name in ready.index:
        design_name = cast(str, design_name)
        design_dir = design_dirs.get(design_name)

        if design_dir is None:
            row: Dict[str, Any] = {
                status_col: f"missing: no output dir for {design_name}",
                path_col: pd.NA,
            }
            row.update({k: pd.NA for k in _get_af3_metrics(af3_dir.name)})
            updates[design_name] = row
            n_missing += 1
            continue

        summary_path, cif_path = find_prediction_files(design_dir)

        if summary_path is None or cif_path is None:
            row = {
                status_col: f"missing: no models in {design_dir}",
                path_col: pd.NA,
            }
            row.update({k: pd.NA for k in _get_af3_metrics(af3_dir.name)})
            updates[design_name] = row
            n_missing += 1
            continue

        try:
            metrics = load_metrics(af3_dir.name, summary_path)
        except (OSError, json.JSONDecodeError) as exc:
            row = {
                status_col: f"error: {exc.__class__.__name__}: {exc}",
                path_col: pd.NA,
            }
            row.update({k: pd.NA for k in _get_af3_metrics(af3_dir.name)})
            updates[design_name] = row
            n_missing += 1
            continue

        row = {
            status_col: "OK",
            path_col: str(cif_path),
        }
        row.update(metrics)
        updates[design_name] = row
        n_filled += 1

    print(
        f"Done. filled={n_filled}, missing={n_missing}, total_considered={len(ready)}"
    )
    return updates
