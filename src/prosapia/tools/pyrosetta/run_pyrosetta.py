#!/usr/bin/env python3
"""
Submit an array (SLURM or Modal) scoring one structure per design with PyRosetta.

Each task loads the design's structure, optionally FastRelaxes it, and records
Rosetta energy metrics (total score, score per residue, every weighted score term,
SASA, packstat, buried unsatisfied H-bonds and, with ``--interface``, interface
dG / dSASA) to a per-design TSV. Use ``sapia collect pyrosetta`` to merge the
results back into the same table under ``pyrosetta_*`` columns.

Structures are staged to PDB at manifest-build time (CIF->PDB cached under
<run_dir>/.cif_to_pdb/), so predictors that emit mmCIF (boltz, alphafold3) work
directly.

Scoring an unrelaxed predicted structure mostly measures the predictor's
clashes and rotamers, not the design; the default of one FastRelax cycle removes
that noise while ``relax_ca_rmsd`` reports how far the structure moved.

Usage:
    # Score Boltz predictions after 1 FastRelax cycle (default)
    sapia run pyrosetta outputs/RUN --table table1

    # Score as-is, into its own column family (pyrosetta_raw_*)
    sapia run pyrosetta outputs/RUN --table table1 --relax-cycles 0 -l raw

    # A binder complex: interface metrics for chain A against chain B
    sapia run pyrosetta outputs/RUN --table table2 --interface A_B
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import cast

from prosapia.core import CommonArgs, ManifestCtx
from prosapia.core.executors import volume_path
from prosapia.utils import ensure_pdb


class PyRosettaArgs(CommonArgs):
    relax_cycles: int
    constrain_relax: bool
    interface: str
    scorefxn: str


def add_run_pyrosetta_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--relax-cycles",
        type=int,
        default=1,
        help="FastRelax repeats before scoring (default 1). 0 scores the structure "
        "as-is; 5 is Rosetta's standard (slower) relax.",
    )
    parser.add_argument(
        "--constrain-relax",
        action="store_true",
        help="Constrain FastRelax to the starting coordinates, so it fixes local "
        "geometry without letting the backbone drift.",
    )
    parser.add_argument(
        "--interface",
        type=str,
        default="",
        help="Interface to analyse with InterfaceAnalyzer, as Rosetta's "
        "'<chains>_<chains>' (e.g. 'A_B', 'AB_C'), or 'auto' for the first chain "
        "against the rest. Empty (default) skips interface metrics.",
    )
    parser.add_argument(
        "--scorefxn",
        type=str,
        default="ref2015",
        help="Rosetta score function (default ref2015).",
    )


def build_pyrosetta_manifest(ctx: ManifestCtx[PyRosettaArgs]) -> list[tuple[str, ...]]:
    ctx.args.gpus_per_task = 0  # CPU-only tool

    if ctx.args.relax_cycles < 0:
        raise ValueError("--relax-cycles must be >= 0")

    relax_cycles = str(ctx.args.relax_cycles)
    constrain = "1" if ctx.args.constrain_relax else "0"

    manifest_rows: list[tuple[str, ...]] = []
    for name in ctx.ready.index:
        name = cast(str, name)
        src = Path(str(ctx.ready.at[name, ctx.args.input_column]))
        # A missing input is passed through raw so the task records it as an error.
        pdb = volume_path(ensure_pdb(src, ctx.args.run_dir)) if src.exists() else src
        manifest_rows.append(
            (
                name,
                str(pdb),
                relax_cycles,
                constrain,
                ctx.args.interface,
                ctx.args.scorefxn,
            )
        )

    return manifest_rows
