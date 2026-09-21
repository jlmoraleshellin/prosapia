#!/usr/bin/env python3
"""
Submit a SLURM array job to run ColabFold predictions on MPNN-designed sequences.

Reads sequences from an MPNN table, groups them into FASTA query files (one per
SLURM task), and submits an sbatch array.

ColabFold dumps all outputs flat into a single directory, so each SLURM task
gets its own ``task_<i>`` output directory.  The companion
``sapia collect colabfold`` scans these task directories to match results back
to design names.

Chains are derived per-sequence from the MPNN chainbreak syntax (``/``-separated
chains) and rendered as ColabFold's ``:``-separated multimer query, so homo- and
hetero-oligomers are handled the same way. ``--chains`` narrows which chains to
predict (mini-language, e.g. ``A:D``). ``--positions`` selects which residues of
each chain to keep (e.g. ``--positions '{prebundle_length+1}:'`` trims an
N-terminal prefix).

Usage:
    sapia run colabfold outputs/20260420_123035_grow_hairpin --table table1
    sapia run colabfold outputs/20260420_123035_grow_hairpin --table table1 --queries-per-task 20 --devices 4
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import cast

from prosapia.core import CommonArgs, ManifestCtx
from prosapia.utils import (
    add_chains_and_positions_args,
    add_devices_arg,
    build_chain_map,
    maybe_set_gpus_per_task,
)


class ColabFoldArgs(CommonArgs):
    queries_per_task: int
    devices: int
    chains: str | None
    positions: str | None


def write_colabfold_fasta(
    fasta_dir: Path,
    task_idx: int,
    queries: list[tuple[str, str]],
) -> Path:
    """Write a multi-query FASTA file for ColabFold.

    Each query's sequence is already the ColabFold multimer string: one sequence
    per chain, ``:``-separated (a single chain has no separator). This covers homo-
    and hetero-oligomers uniformly.
    """
    fasta_path = fasta_dir / f"query_{task_idx}.fasta"
    with open(fasta_path, "w") as f:
        for name, multimer_seq in queries:
            f.write(f">{name}\n{multimer_seq}\n")
    return fasta_path


def add_colabfold_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--queries-per-task",
        type=int,
        default=10,
        help="Number of queries per FASTA file (i.e. per SLURM task). Defaults to 10.",
    )
    add_devices_arg(parser)
    add_chains_and_positions_args(parser)


def build_colabfold_manifest(ctx: ManifestCtx[ColabFoldArgs]):
    maybe_set_gpus_per_task(ctx.args)

    fasta_dir = ctx.out_dir / "colabfold_queries"
    fasta_dir.mkdir(parents=True, exist_ok=True)

    queries: list[tuple[str, str]] = []
    for name in ctx.ready.index:
        name = cast(str, name)
        sequence = str(ctx.ready.at[name, ctx.args.input_column])
        chain_map = build_chain_map(
            sequence, ctx.args.chains, ctx.args.positions, ctx.lookup, name
        )
        multimer_seq = ":".join(chain_map.values())
        queries.append((name, multimer_seq))

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(queries), ctx.args.queries_per_task):
        batch = queries[i : i + ctx.args.queries_per_task]
        task_idx = i // ctx.args.queries_per_task
        fasta_path = write_colabfold_fasta(fasta_dir, task_idx, batch)
        manifest_rows.append((str(fasta_path),))

    return manifest_rows
