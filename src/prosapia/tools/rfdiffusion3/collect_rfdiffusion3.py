#!/usr/bin/env python3
"""
Collect RFdiffusion3 outputs into the (child) diffusion database.

``rfd3 design`` writes, per design key, files named:

    <shard_stem>_<key>_<batch>_model_<n>.cif.gz   (compressed CIF structure)
    <shard_stem>_<key>_<batch>_model_<n>.json     (per-design metadata)

into ``<out_dir>/results_<shard_stem>/``. This scans those dirs, matches files
back to their parent design (the JSON key == a parent-db row name), converts each
``.cif.gz`` to PDB (downstream tools consume PDB), and registers one child row per
output as ``<name>_<i>`` carrying ``parent_name`` for lineage.

Safe to re-run: rows are rebuilt from the outputs on disk.

Usage:
    sapia collect rfdiffusion3 outputs/RUN --database db2
"""

import json
import re
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, cast

import pandas as pd

from prosapia.core import (
    PARENT_NAME,
    CollectArgs,
    CollectCtx,
    CollectResult,
    ensure_pdb,
)

# Metadata keys pulled from the per-design sidecar JSON when present.
RFD3_METADATA_KEYS = ["ca_rmsd_to_input"]


class RFD3CollectArgs(CollectArgs):
    num_designs: int


def _add_rfd3_collect_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--num-designs",
        type=int,
        default=1,
        help="Expected outputs per parent (used to mark parents with no outputs "
        "as errors). Defaults to 1.",
    )


def _load_metadata(json_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(json_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {f"rfd3_{k}": pd.NA for k in RFD3_METADATA_KEYS}
    return {f"rfd3_{k}": data.get(k, pd.NA) for k in RFD3_METADATA_KEYS}


def _find_outputs(results_dirs: list[Path], name: str) -> list[tuple[int, int, Path]]:
    """Return [(batch, model, cif_gz_path), ...] for a parent ``name``, sorted."""
    pattern = re.compile(rf".+_{re.escape(name)}_(\d+)_model_(\d+)\.cif\.gz$")
    found: list[tuple[int, int, Path]] = []
    for results_dir in results_dirs:
        for cif in results_dir.glob(f"*_{name}_*_model_*.cif.gz"):
            m = pattern.match(cif.name)
            if m:
                found.append((int(m.group(1)), int(m.group(2)), cif))
    found.sort(key=lambda t: (t[0], t[1]))
    return found


def collect_rfd3(ctx: CollectCtx) -> CollectResult:
    results_dirs = sorted(d for d in ctx.out_dir.glob("results_*") if d.is_dir())
    print(f"Scanning {len(results_dirs)} results dir(s) in {ctx.out_dir}")

    # Parent rows are the design keys we wrote into the shard JSONs. ctx.ready
    # drops parents with an NA input column (a create tool rebuilds from disk).
    parent_names = [cast(str, n) for n in ctx.ready.index]

    updates: CollectResult = {}
    n_ok = 0
    n_failed_parents = 0

    for name in parent_names:
        outputs = _find_outputs(results_dirs, name)

        if not outputs:
            n_failed_parents += 1
            print(f"{name}: no outputs, marking {ctx.args.num_designs} row(s) as error")
            for i in range(ctx.args.num_designs):
                updates[f"{name}_{i}"] = {
                    PARENT_NAME: name,
                    "iteration": i,
                    ctx.status_col: "error: no output",
                    ctx.path_col: pd.NA,
                }
            continue

        for i, (batch, model, cif_gz) in enumerate(outputs):
            pdb_path = ensure_pdb(cif_gz, ctx.args.run_dir)
            row: dict[str, Any] = {
                PARENT_NAME: name,
                "iteration": i,
                "rfd3_batch": batch,
                "rfd3_model": model,
                ctx.status_col: "OK",
                ctx.path_col: str(pdb_path),
            }
            row.update(_load_metadata(cif_gz.with_suffix("").with_suffix(".json")))
            updates[f"{name}_{i}"] = row
            n_ok += 1

        print(f"{name}: OK ({len(outputs)} output(s))")

    print(
        f"\nDone. {len(updates)} row(s): {n_ok} OK, {n_failed_parents} failed parent(s)."
    )
    return updates
