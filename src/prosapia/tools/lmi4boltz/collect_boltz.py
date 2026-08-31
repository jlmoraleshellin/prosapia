#!/usr/bin/env python3
"""
Collect boltz prediction results into mpnn_db.

For each row in mpnn_db that was submitted to boltz, look for:

    <run_dir>/<boltz_dir>/boltz_results_*/predictions/<row>/
        confidence_<row>_model_0.json   -> metrics
        <row>_model_0.cif               -> model file

Supports both per-design results (boltz_results_<row>/) and shard results
(boltz_results_shard_i/). Writes the metrics + path into the row.

Usage:
    sapia collect boltz outputs/RUN --database db1_..._mpnn_seqs
    sapia collect boltz outputs/RUN --database db1_..._mpnn_seqs --force
"""

import json
from pathlib import Path
from typing import Any, Dict, List, cast

import pandas as pd

from prosapia.core import CollectCtx, CollectResult

# Top-level scalar metrics to copy from the boltz confidence JSON.
# Matches the first 9 keys in boltz's confidence_*_model_0.json output.
BOLTZ_METRICS: List[str] = [
    "confidence_score",
    "ptm",
    "iptm",
    "ligand_iptm",
    "protein_iptm",
    "complex_plddt",
    "complex_iplddt",
    "complex_pde",
    "complex_ipde",
]


def find_prediction_files(
    boltz_dir: Path,
    design_name: str,
    prediction_dirs: dict[str, Path],
) -> tuple[Path | None, Path | None, Path | None]:
    """Return (confidence_json, model_cif, plddt_npz) for a design.

    Falls back to globbing if model_0 isn't present, picking the lowest-numbered
    model.
    """
    pred_dir = prediction_dirs.get(design_name)
    if pred_dir is None:
        return None, None, None

    json_default = pred_dir / f"confidence_{design_name}_model_0.json"
    cif_default = pred_dir / f"{design_name}_model_0.cif"
    plddt_default = pred_dir / f"plddt_{design_name}_model_0.npz"

    if json_default.exists() and cif_default.exists():
        plddt_path = plddt_default if plddt_default.exists() else None
        return json_default, cif_default, plddt_path

    json_candidates = sorted(pred_dir.glob(f"confidence_{design_name}_model_*.json"))
    cif_candidates = sorted(pred_dir.glob(f"{design_name}_model_*.cif"))
    if not json_candidates or not cif_candidates:
        return None, None, None

    plddt_candidates = sorted(pred_dir.glob(f"plddt_{design_name}_model_*.npz"))
    plddt_path = plddt_candidates[0] if plddt_candidates else None
    return json_candidates[0], cif_candidates[0], plddt_path


def load_metrics(json_path: Path) -> Dict[str, Any]:
    """Read the configured top-level scalar metrics from a boltz confidence JSON."""
    with open(json_path) as f:
        data = json.load(f)
    return {f"boltz_{k}": data.get(k, pd.NA) for k in BOLTZ_METRICS}


def collect_boltz(ctx: CollectCtx) -> CollectResult:
    if ctx.df.empty:
        raise RuntimeError(
            f"Database {ctx.args.database!r} is empty or missing in {ctx.args.run_dir}."
        )

    ready = ctx.ready

    if not ctx.args.force and ctx.path_col in ctx.df.columns:
        existing = ctx.df.loc[ready.index, ctx.path_col]
        already_done = ready.index[existing.notna() & (existing != "")]
        if len(already_done) > 0:
            print(
                f"Skipping {len(already_done)} already-collected design(s) "
                f"(use --force to re-collect)"
            )
            ready = ready.drop(already_done)

    # Build a map of design_name -> prediction dir across all boltz_results_* dirs.
    prediction_dirs: dict[str, Path] = {}
    for results_dir in sorted(ctx.out_dir.glob("boltz_results_*")):
        preds = results_dir / "predictions"
        if not preds.is_dir():
            continue
        for design_dir in preds.iterdir():
            if design_dir.is_dir():
                prediction_dirs[design_dir.name] = design_dir

    updates: CollectResult = {}
    n_filled = 0
    n_missing = 0
    for design_name in ready.index:
        design_name = cast(str, design_name)
        json_path, cif_path, plddt_path = find_prediction_files(
            ctx.out_dir,
            design_name,
            prediction_dirs,
        )

        if json_path is None or cif_path is None:
            row: Dict[str, Any] = {
                ctx.status_col: f"missing: boltz_results_{design_name}",
                ctx.path_col: pd.NA,
            }
            row.update({f"boltz_{k}": pd.NA for k in BOLTZ_METRICS})
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
            row.update({f"boltz_{k}": pd.NA for k in BOLTZ_METRICS})
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
