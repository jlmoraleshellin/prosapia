#!/usr/bin/env python3
"""
Collect OpenFold3 prediction results into the database.

Scans task directories for prediction outputs, picks the best-scoring model
per design (highest avg_plddt across all seeds/samples), and writes metrics
+ model path into the database.

Output structure expected:

    <openfold3_dir>/task_<i>/<design_name>/seed_<x>/
        <design_name>_seed_<x>_sample_<N>_model.cif
        <design_name>_seed_<x>_sample_<N>_confidences_aggregated.json

Usage:
    sapia collect openfold3 outputs/RUN --database db1_..._mpnn_seqs
    sapia collect openfold3 outputs/RUN --database db1_..._mpnn_seqs --force
"""

import json
from pathlib import Path
from typing import Any, Dict, List, cast

import pandas as pd

from prosapia.core import CollectCtx, CollectResult

OPENFOLD3_JSON_KEYS: List[str] = [
    "avg_plddt",
    "gpde",
    "iptm",
    "ptm",
    "disorder",
    "has_clash",
    "sample_ranking_score",
]

OPENFOLD3_METRICS: List[str] = [f"openfold_{k}" for k in OPENFOLD3_JSON_KEYS]


def find_best_model(design_dir: Path) -> tuple[Path | None, Path | None]:
    """Find the best model across all seeds/samples by highest avg_plddt.
    Handles multiple seeds and samples per seed, returns only one model per design dir.

    Returns (confidence_json, model_cif) for the best model, or (None, None).
    """
    best_plddt = -1.0
    best_json: Path | None = None
    best_cif: Path | None = None

    for seed_dir in sorted(design_dir.iterdir()):
        if not seed_dir.is_dir() or not seed_dir.name.startswith("seed_"):
            continue
        for conf_path in sorted(seed_dir.glob("*_confidences_aggregated.json")):
            try:
                with open(conf_path) as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            plddt = data.get("avg_plddt", -1.0)
            if plddt <= best_plddt:
                continue

            stem = conf_path.name.replace("_confidences_aggregated.json", "_model.cif")
            cif_path = seed_dir / stem
            if not cif_path.exists():
                continue

            best_plddt = plddt
            best_json = conf_path
            best_cif = cif_path

    return best_json, best_cif


def load_metrics(json_path: Path) -> Dict[str, Any]:
    with open(json_path) as f:
        data = json.load(f)
    return {f"openfold_{k}": data.get(k, pd.NA) for k in OPENFOLD3_JSON_KEYS}


def collect_openfold3(ctx: CollectCtx) -> CollectResult:
    if ctx.df.empty:
        raise RuntimeError(
            f"Database {ctx.args.database!r} is empty or missing in {ctx.args.run_dir}."
        )

    ready = ctx.ready

    # Build a map of design_name -> design_dir across all task directories.
    design_dirs: dict[str, Path] = {}
    for task_dir in sorted(ctx.out_dir.iterdir()):
        if not task_dir.is_dir() or not task_dir.name.startswith("task_"):
            continue
        for design_dir in task_dir.iterdir():
            if design_dir.is_dir():
                design_dirs[design_dir.name] = design_dir

    updates: CollectResult = {}
    n_filled = 0
    n_missing = 0
    # Iterate over ready designs and check for best model in the design directory
    for design_name in ready.index:
        design_name = cast(str, design_name)
        design_dir = design_dirs.get(design_name)

        if design_dir is None:
            row: Dict[str, Any] = {
                ctx.status_col: f"missing: no task dir for {design_name}",
                ctx.path_col: pd.NA,
            }
            row.update({k: pd.NA for k in OPENFOLD3_METRICS})
            updates[design_name] = row
            n_missing += 1
            continue

        json_path, cif_path = find_best_model(design_dir)

        if json_path is None or cif_path is None:
            row = {
                ctx.status_col: f"missing: no models in {design_dir}",
                ctx.path_col: pd.NA,
            }
            row.update({k: pd.NA for k in OPENFOLD3_METRICS})
            updates[design_name] = row
            n_missing += 1
            continue

        try:
            metrics = load_metrics(json_path)
        except (OSError, json.JSONDecodeError) as exc:
            row = {
                ctx.status_col: f"error: {exc.__class__.__name__}: {exc}",
                ctx.path_col: pd.NA,
            }
            row.update({k: pd.NA for k in OPENFOLD3_METRICS})
            updates[design_name] = row
            n_missing += 1
            continue

        row = {ctx.status_col: "OK", ctx.path_col: str(cif_path)}
        row.update(metrics)
        updates[design_name] = row
        n_filled += 1

    print(
        f"Done. filled={n_filled}, missing={n_missing}, total_considered={len(ready)}"
    )
    return updates
