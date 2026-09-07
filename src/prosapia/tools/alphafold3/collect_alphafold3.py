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
    sapia collect alphafold3 outputs/20260420_123035_grow_hairpin --database db1_..._mpnn_seqs
    sapia collect alphafold3 outputs/20260420_123035_grow_hairpin --database db1_..._mpnn_seqs --force
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from prosapia.core import (
    Collected,
    CollectCtx,
    CollectEach,
    DesignCtx,
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


def collect_af3(ctx: CollectCtx) -> CollectEach:
    """Per-design AF3 collector. The framework iterates ready designs and stamps
    status/path; this only locates + parses one design's output."""
    if ctx.df.empty:
        raise RuntimeError(
            f"Database {ctx.args.database!r} is empty or missing in {ctx.args.run_dir}."
        )

    # Index every predicted design dir once, up front.
    design_dirs: dict[str, Path] = {}
    for shard_dir in sorted(ctx.out_dir.glob("results_shard_*")):
        if not shard_dir.is_dir():
            continue
        for design_dir in shard_dir.iterdir():
            if design_dir.is_dir():
                design_dirs[design_dir.name] = design_dir

    # Failure rows keep the metric columns present (as NA) so the frame's schema
    # is stable even when every design fails.
    na_metrics: Dict[str, Any] = {k: pd.NA for k in _get_af3_metrics(ctx.out_dir.name)}

    def one(d: DesignCtx) -> Iterable[Collected]:
        design_dir = design_dirs.get(d.name)
        if design_dir is None:
            yield Collected(
                status=f"missing: no output dir for {d.name}", data=na_metrics
            )
            return

        summary_path, cif_path = find_prediction_files(design_dir)
        if summary_path is None or cif_path is None:
            yield Collected(
                status=f"missing: no models in {design_dir}", data=na_metrics
            )
            return

        try:
            metrics = load_metrics(d.leaf, summary_path)
        except (OSError, json.JSONDecodeError) as exc:
            yield Collected(
                status=f"error: {exc.__class__.__name__}: {exc}", data=na_metrics
            )
            return

        yield Collected(data=metrics, path=cif_path)

    return one
