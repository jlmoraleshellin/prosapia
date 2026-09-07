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
from typing import Any, Dict, Iterable, List

import pandas as pd

from prosapia.core import Collected, CollectCtx, CollectEach, DesignCtx

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


def collect_boltz(ctx: CollectCtx) -> CollectEach:
    """Per-design boltz collector. The framework iterates ready designs and stamps
    status/path; this only locates + parses one design's prediction."""
    if ctx.df.empty:
        raise RuntimeError(
            f"Database {ctx.args.database!r} is empty or missing in {ctx.args.run_dir}."
        )

    # Build a map of design_name -> prediction dir across all boltz_results_* dirs.
    prediction_dirs: dict[str, Path] = {}
    for results_dir in sorted(ctx.out_dir.glob("boltz_results_*")):
        preds = results_dir / "predictions"
        if not preds.is_dir():
            continue
        for design_dir in preds.iterdir():
            if design_dir.is_dir():
                prediction_dirs[design_dir.name] = design_dir

    na_metrics: Dict[str, Any] = {f"boltz_{k}": pd.NA for k in BOLTZ_METRICS}

    def one(d: DesignCtx) -> Iterable[Collected]:
        json_path, cif_path, _plddt_path = find_prediction_files(
            ctx.out_dir, d.name, prediction_dirs
        )

        if json_path is None or cif_path is None:
            yield Collected(status=f"missing: boltz_results_{d.name}", data=na_metrics)
            return

        try:
            metrics = load_metrics(json_path)
        except (OSError, json.JSONDecodeError) as exc:
            yield Collected(
                status=f"error: {exc.__class__.__name__}: {exc}", data=na_metrics
            )
            return

        yield Collected(data=metrics, path=cif_path)

    return one
