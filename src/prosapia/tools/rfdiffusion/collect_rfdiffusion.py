#!/usr/bin/env python3
"""
Rebuild the diffusion table from a run directory's diffused/ outputs.

For each parent design folder under <run_dir>/<diffused-dir-name>/, this looks
for a command.txt marker file (written by rfdiffusion.sbatch once a task has
run) and, if present, registers every <name>_<i>.pdb it finds as an OK row in the
diffusion table. Parents missing the marker file (or with no PDBs) contribute no rows.

Run this after the rfdiffusion SLURM array; it (re)builds the diffusion table by
scanning the outputs, so it is safe to re-run to rebuild a corrupted table.

Usage:
    sapia collect rfdiffusion outputs/RUN --table table1
"""

import re
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


def collect_diffusion(ctx: CollectCtx[CollectArgs]) -> CollectEach:
    """Per-parent rfdiffusion collector. rfdiffusion is a create tool: the framework
    iterates the ready parents and this rebuilds each parent's child rows from the
    diffused PDBs found in its on-disk output dir (out_dir/<name>/). A parent with no
    dir/marker yields no rows. The framework stamps status/path/parent_name from each
    Collected."""

    def one(d: DesignCtx) -> Iterable[Collected]:
        parent_dir = ctx.out_dir / d.name

        if not (parent_dir / MARKER_FILENAME).exists():
            print(f"{d.name}: no {MARKER_FILENAME}, skipping")
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
