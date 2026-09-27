"""SLURM executor: one ``sbatch --array`` per manifest chunk (and per partition)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from . import SubmitCtx, write_manifest

if TYPE_CHECKING:
    from ..base_sbatch import ManifestRow

SLURM_MAX_ARRAY_SIZE = int(os.getenv("SLURM_MAX_ARRAY_SIZE", 1000))


def submit(ctx: SubmitCtx) -> None:
    """Submit the manifest rows as SLURM arrays, chunking into groups of
    SLURM_MAX_ARRAY_SIZE (and splitting across ``--partitions`` when set)."""
    if ctx.args.partitions:
        _submit_multi_partition(ctx)
    else:
        _submit_chunked(ctx, ctx.rows, ctx.manifest_base, ctx.args.max_concurrent)


def _query_partition_gpus(partition: str) -> int:
    """Query total GPU count for a SLURM partition via ``sinfo``."""
    result = subprocess.run(
        ["sinfo", "-p", partition, "-h", "-N", "-o", "%G"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"sinfo failed for partition {partition!r}: {result.stderr.strip()}\n"
            f"Specify GPU counts explicitly: --partitions {partition}:<gpu_count>"
        )
    total = 0
    for line in result.stdout.strip().splitlines():
        for entry in line.split(","):
            if entry.startswith("gpu"):
                parts = entry.split(":")
                total += int(parts[-1])
    if total == 0:
        raise RuntimeError(
            f"No GPUs found in partition {partition!r}. "
            f"Specify GPU counts explicitly: --partitions {partition}:<gpu_count>"
        )
    return total


def _submit_array(
    ctx: SubmitCtx,
    manifest: Path,
    n_tasks: int,
    max_concurrent: int,
    partition: str | None = None,
) -> None:
    args = ctx.args
    cmd = [
        "sbatch",
        f"--account={args.account}" if args.account else "",
        f"--array=1-{n_tasks}%{max_concurrent}",
        f"--partition={partition}" if partition else "",
        f"--gres=gpu:{args.gpus_per_task}" if args.gpus_per_task > 0 else "",
        f"--cpus-per-task={args.cpus_per_task}" if args.cpus_per_task else "",
        f"--time={args.time}" if args.time else "",
        f"--mem={args.mem}" if args.mem else "",
        f"--output={ctx.log_dir}/{ctx.script.stem}_%A_%a.out",
        f"--error={ctx.log_dir}/{ctx.script.stem}_%A_%a.err",
        str(ctx.script),
        str(manifest),
        str(ctx.out_dir),
    ]
    cmd = [c for c in cmd if c]  # Remove empty arguments
    print("Submitting:", " ".join(cmd))
    result = subprocess.run(cmd, env={**os.environ, **ctx.task_env("slurm")})
    if result.returncode != 0:
        raise RuntimeError(f"sbatch exited {result.returncode}")


def _submit_chunked(
    ctx: SubmitCtx,
    rows: "Sequence[ManifestRow]",
    manifest_base: Path,
    max_concurrent: int,
    partition: str | None = None,
) -> None:
    """Split rows into chunks of SLURM_MAX_ARRAY_SIZE, write a manifest for
    each chunk, and submit separate array jobs."""
    chunks = [
        rows[i : i + SLURM_MAX_ARRAY_SIZE]
        for i in range(0, len(rows), SLURM_MAX_ARRAY_SIZE)
    ]

    for chunk_idx, chunk in enumerate(chunks):
        if len(chunks) == 1:
            manifest = manifest_base
        else:
            manifest = manifest_base.with_stem(f"{manifest_base.stem}_{chunk_idx}")
        write_manifest(manifest, chunk)

        if partition or len(chunks) > 1:
            parts = []
            if partition:
                parts.append(partition)
            if len(chunks) > 1:
                parts.append(f"chunk {chunk_idx + 1}/{len(chunks)}")
            print(f"[{', '.join(parts)}]")

        _submit_array(ctx, manifest, len(chunk), max_concurrent, partition)


def _submit_multi_partition(ctx: SubmitCtx) -> None:
    """Submit one SLURM array per partition, each capped at a GPU fraction.
    Each partition's share is further chunked to respect SLURM_MAX_ARRAY_SIZE."""
    args = ctx.args

    def parse_partitions(raw: str) -> list[tuple[str, int | None]]:
        """Parse ``'part1[:gpus],part2[:gpus]'`` into (name, gpu_count | None)."""
        result: list[tuple[str, int | None]] = []
        for token in raw.split(","):
            if ":" in token:
                name, count = token.rsplit(":", 1)
                result.append((name, int(count)))
            else:
                result.append((token, None))
        return result

    parsed = parse_partitions(args.partitions)  # type: ignore[arg-type]

    partition_caps: list[tuple[str, int]] = []
    for name, gpu_count in parsed:
        if gpu_count is None:
            gpu_count = _query_partition_gpus(name)
        cap = max(1, int(gpu_count * args.max_gpu_fraction) // args.gpus_per_task)
        partition_caps.append((name, cap))

    n_tasks = len(ctx.rows)
    n_parts = len(partition_caps)
    chunk = n_tasks // n_parts
    remainder = n_tasks % n_parts
    start = 0
    for i, (partition, cap) in enumerate(partition_caps):
        size = chunk + (1 if i < remainder else 0)
        if size == 0:
            continue
        partition_rows = ctx.rows[start : start + size]
        part_manifest = ctx.manifest_base.with_stem(
            f"{ctx.manifest_base.stem}_{partition}"
        )
        _submit_chunked(ctx, partition_rows, part_manifest, cap, partition)
        start += size
