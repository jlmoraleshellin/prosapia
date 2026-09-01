#!/usr/bin/env python3
"""
Rebuild the diffusion database from a run directory's diffused/ outputs.

For each parent design folder under <run_dir>/<diffused-dir-name>/, this looks
for a command.txt marker file (written by rfdiffusion.sbatch once a task has
run) and, if present, registers every <name>_<i>.pdb it finds as an OK row in the
diffusion DB. Parents missing the marker file get an "error: no marker" row per
expected iteration.

Run this after the rfdiffusion SLURM array; it (re)builds the diffusion db by
scanning the outputs, so it is safe to re-run to rebuild a corrupted db.

Usage:
    sapia collect rfdiffusion outputs/RUN --database db1
"""

import re
from argparse import ArgumentParser
from pathlib import Path
from typing import cast

import pandas as pd

from prosapia.core import (
    PARENT_NAME,
    CollectArgs,
    CollectCtx,
    CollectResult,
)

MARKER_FILENAME = "command.txt"


def _find_diffused_pdbs(parent_dir: Path, name: str) -> list[tuple[int, Path]]:
    """Return [(iteration, pdb_path), ...] sorted by iteration."""
    pattern = re.compile(rf"^{re.escape(name)}_(\d+)\.pdb$")
    found: list[tuple[int, Path]] = []
    for pdb in parent_dir.glob(f"{name}_*.pdb"):
        m = pattern.match(pdb.name)
        if m:
            found.append((int(m.group(1)), pdb))
    found.sort(key=lambda t: t[0])
    return found


class DiffusionCollectArgs(CollectArgs):
    num_designs: int


def _add_diffusion_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--num-designs",
        type=int,
        default=10,
        help="Expected number of iterations per parent (used when marking "
        "failed parents). Defaults to 10.",
    )


def collect_diffusion(ctx: CollectCtx) -> CollectResult:
    updates: CollectResult = {}
    n_ok = 0
    n_failed_parents = 0

    # rfdiffusion is a create tool: iterate the ready parents and rebuild child
    # rows from each parent's on-disk output dir (out_dir/<name>/). A parent with
    # no dir/marker is marked failed, like a parent whose run produced no marker.
    for name in ctx.ready.index:
        name = cast(str, name)  # the parent row (a design in the input db)
        parent_dir = ctx.out_dir / name
        marker = parent_dir / MARKER_FILENAME

        if not marker.exists():
            # No success marker -- treat the whole parent as failed.
            n_failed_parents += 1
            print(
                f"{name}: no {MARKER_FILENAME}, marking "
                f"{ctx.args.num_designs} row(s) as error"
            )
            for i in range(ctx.args.num_designs):
                updates[f"{name}_{i}"] = {
                    PARENT_NAME: name,
                    "iteration": i,
                    ctx.status_col: "error: no marker",
                    ctx.path_col: pd.NA,
                }
            continue

        pdbs = _find_diffused_pdbs(parent_dir, name)
        if not pdbs:
            print(f"{name}: marker present but no PDBs found")
            continue

        for i, pdb_path in pdbs:
            updates[f"{name}_{i}"] = {
                PARENT_NAME: name,
                "iteration": i,
                ctx.status_col: "OK",
                ctx.path_col: str(pdb_path),
            }
            n_ok += 1

        print(f"{name}: OK ({len(pdbs)} iteration(s))")

    print(
        f"\nDone. {len(updates)} row(s): {n_ok} OK, {n_failed_parents} failed parent(s)."
    )
    return updates
