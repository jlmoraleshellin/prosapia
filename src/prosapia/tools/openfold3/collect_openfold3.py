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
from typing import Any, Dict, Iterable, List

import pandas as pd

from prosapia.core import Collected, CollectCtx, CollectEach, DesignCtx

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


def collect_openfold3(ctx: CollectCtx) -> CollectEach:
    """Per-design OpenFold3 collector. The framework iterates ready designs and
    stamps status/path; this only locates the best model for one design."""
    if ctx.df.empty:
        raise RuntimeError(
            f"Database {ctx.args.database!r} is empty or missing in {ctx.args.run_dir}."
        )

    # Build a map of design_name -> design_dir across all task directories.
    design_dirs: dict[str, Path] = {}
    for task_dir in sorted(ctx.out_dir.iterdir()):
        if not task_dir.is_dir() or not task_dir.name.startswith("task_"):
            continue
        for design_dir in task_dir.iterdir():
            if design_dir.is_dir():
                design_dirs[design_dir.name] = design_dir

    na_metrics: Dict[str, Any] = {k: pd.NA for k in OPENFOLD3_METRICS}

    def one(d: DesignCtx) -> Iterable[Collected]:
        design_dir = design_dirs.get(d.name)
        if design_dir is None:
            yield Collected(
                status=f"missing: no task dir for {d.name}", data=na_metrics
            )
            return

        json_path, cif_path = find_best_model(design_dir)
        if json_path is None or cif_path is None:
            yield Collected(
                status=f"missing: no models in {design_dir}", data=na_metrics
            )
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
