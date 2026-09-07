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
from typing import Iterable

from prosapia.core import (
    Collected,
    CollectArgs,
    CollectCtx,
    CollectEach,
    DesignCtx,
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


def collect_diffusion(ctx: CollectCtx[DiffusionCollectArgs]) -> CollectEach:
    """Per-parent rfdiffusion collector. rfdiffusion is a create tool: the framework
    iterates the ready parents and this rebuilds each parent's child rows from its
    on-disk output dir (out_dir/<name>/). A parent with no dir/marker is marked
    failed. The framework stamps status/path/parent_name from each Collected."""
    num_designs = ctx.args.num_designs

    def one(d: DesignCtx) -> Iterable[Collected]:
        parent_dir = ctx.out_dir / d.name
        marker = parent_dir / MARKER_FILENAME

        if not marker.exists():
            # No success marker -- treat the whole parent as failed.
            print(
                f"{d.name}: no {MARKER_FILENAME}, marking {num_designs} row(s) as error"
            )
            for i in range(num_designs):
                yield Collected(
                    name=f"{d.name}_{i}",
                    parent=d.name,
                    status="error: no marker",
                    data={"iteration": i},
                )
            return

        pdbs = _find_diffused_pdbs(parent_dir, d.name)
        if not pdbs:
            print(f"{d.name}: marker present but no PDBs found")
            return

        for i, pdb_path in pdbs:
            yield Collected(
                name=f"{d.name}_{i}",
                parent=d.name,
                path=pdb_path,
                data={"iteration": i},
            )
        print(f"{d.name}: OK ({len(pdbs)} iteration(s))")

    return one
