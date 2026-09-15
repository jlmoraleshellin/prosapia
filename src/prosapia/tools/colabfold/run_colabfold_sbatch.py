#!/usr/bin/env python3
"""
Submit a SLURM array job to run ColabFold predictions on MPNN-designed sequences.

Reads sequences from an MPNN table, trims N-terminal residues based on
--start-at-column, groups them into FASTA query files (one per SLURM task),
and submits an sbatch array.

ColabFold dumps all outputs flat into a single directory, so each SLURM task
gets its own ``task_<i>`` output directory.  The companion
``sapia collect colabfold`` scans these task directories to match results back
to design names.

Chains are derived per-sequence from the MPNN chainbreak syntax (``/``-separated
chains) and rendered as ColabFold's ``:``-separated multimer query, so homo- and
hetero-oligomers are handled the same way. ``--chains`` narrows which chains to
predict (mini-language, e.g. ``A:D``). ``--start-at-column`` still trims N-terminal
residues (per chain), reading e.g. a ``prebundle_length`` column up the lineage.

Usage:
    sapia run colabfold outputs/20260420_123035_grow_hairpin --table table1
    sapia run colabfold outputs/20260420_123035_grow_hairpin --table table1 --queries-per-task 20 --devices 4
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import cast

from prosapia.core import CommonArgs, ManifestCtx
from prosapia.utils import select_chains


class ColabFoldArgs(CommonArgs):
    queries_per_task: int
    devices: int
    start_at_column: str
    chains: str | None


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


def _add_colabfold_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--queries-per-task",
        type=int,
        default=10,
        help="Number of queries per FASTA file (i.e. per SLURM task). Defaults to 10.",
    )
    parser.add_argument(
        "--devices",
        type=int,
        default=1,
        help="Number of GPUs per task. "
        "Automatically sets --gpus-per-task to match unless explicitly overridden. "
        "Defaults to 1.",
    )
    parser.add_argument(
        "--chains",
        type=str,
        default=None,
        metavar="A:D",
        help="Chains to predict, in the chain mini-language (':' inclusive letter "
        "range, ',' separates): e.g. 'A:D' -> A, B, C, D. Selects those chains from "
        "the input sequence; letters beyond the sequence's chain count are dropped. "
        "Default: predict every chain in the sequence.",
    )
    parser.add_argument(
        "--start-at-column",
        type=str,
        default="prebundle_length",
        help="Column whose value determines how many N-terminal residues to trim. "
        "Use 'none' to use the full sequence. Defaults to 'prebundle_length'.",
    )


def build_colabfold_manifest(ctx: ManifestCtx[ColabFoldArgs]):
    if ctx.args.devices > 1:
        ctx.args.gpus_per_task = ctx.args.devices

    fasta_dir = ctx.out_dir / "colabfold_queries"
    fasta_dir.mkdir(parents=True, exist_ok=True)

    ready = ctx.ready

    start_at_col: str | None = ctx.args.start_at_column
    if start_at_col and start_at_col.lower() == "none":
        start_at_col = None

    queries: list[tuple[str, str]] = []
    for name in ready.index:
        name = cast(str, name)
        sequence = str(ready.at[name, ctx.args.input_column])
        chain_map = select_chains(sequence, ctx.args.chains)
        if start_at_col:
            start_at = int(ready.at[name, start_at_col])  # type: ignore
            chain_map = {c: seq[start_at:] for c, seq in chain_map.items()}
        multimer_seq = ":".join(chain_map.values())
        queries.append((name, multimer_seq))

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(queries), ctx.args.queries_per_task):
        batch = queries[i : i + ctx.args.queries_per_task]
        task_idx = i // ctx.args.queries_per_task
        fasta_path = write_colabfold_fasta(fasta_dir, task_idx, batch)
        manifest_rows.append((str(fasta_path),))

    return manifest_rows
