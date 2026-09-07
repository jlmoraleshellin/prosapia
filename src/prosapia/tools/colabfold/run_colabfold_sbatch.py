#!/usr/bin/env python3
"""
Submit a SLURM array job to run ColabFold predictions on MPNN-designed sequences.

Reads sequences from an MPNN database, trims N-terminal residues based on
--start-at-column, groups them into FASTA query files (one per SLURM task),
and submits an sbatch array.

ColabFold dumps all outputs flat into a single directory, so each SLURM task
gets its own ``task_<i>`` output directory.  The companion
``sapia collect colabfold`` scans these task directories to match results back
to design names.

Requires ``n_subunits`` and (optionally) ``prebundle_length`` columns available
up the input db's lineage (resolved via ``DataManager.lookup``).

Usage:
    sapia run colabfold outputs/20260420_123035_grow_hairpin --database db1_..._mpnn_seqs
    sapia run colabfold outputs/20260420_123035_grow_hairpin --database db1_..._mpnn_seqs --queries-per-task 20 --devices 4
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import cast

from prosapia.core import CommonArgs, ManifestCtx


class ColabFoldArgs(CommonArgs):
    queries_per_task: int
    devices: int
    start_at_column: str
    n_subunits: int | None


def write_colabfold_fasta(
    fasta_dir: Path,
    task_idx: int,
    queries: list[tuple[str, str, int]],
) -> Path:
    """Write a multi-query FASTA file for ColabFold.

    For homo-oligomers the sequence is repeated with ``:`` separators so
    ColabFold treats each copy as a separate chain.
    """
    fasta_path = fasta_dir / f"query_{task_idx}.fasta"
    with open(fasta_path, "w") as f:
        for name, sequence, n_subunits in queries:
            multimer_seq = (
                ":".join([sequence] * n_subunits) if n_subunits > 1 else sequence
            )
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
        "--n-subunits",
        type=int,
        default=None,
        help="Fixed number of subunits for all designs. "
        "When set, overrides the 'n_subunits' DB column.",
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

    queries: list[tuple[str, str, int]] = []
    for name in ready.index:
        name = cast(str, name)
        sequence = str(ready.at[name, ctx.args.input_column]).split("/", 1)[0]
        if start_at_col:
            start_at = int(ready.at[name, start_at_col])  # type: ignore
            sequence = sequence[start_at:]
        n_subunits = ctx.args.n_subunits or int(ctx.lookup(name, "n_subunits"))
        queries.append((name, sequence, n_subunits))

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(queries), ctx.args.queries_per_task):
        batch = queries[i : i + ctx.args.queries_per_task]
        task_idx = i // ctx.args.queries_per_task
        fasta_path = write_colabfold_fasta(fasta_dir, task_idx, batch)
        manifest_rows.append((str(fasta_path),))

    return manifest_rows
