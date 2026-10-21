"""Local executor: run the manifest on this machine, a few tasks at a time.

Each task runs the tool's unchanged ``<tool>.sh`` as a subprocess, exactly as a
SLURM array task would: same ``<script> <manifest> <out_dir>`` argv, same task env,
``SAPIA_TASK_ID`` selecting its manifest line, and the activation script sourced
through ``sapia_activate`` (``SAPIA_SCHEDULER=local``).

Concurrency is a fixed set of *slots*, each holding one task at a time:

- GPU tasks (``--gpus-per-task N > 0``): one slot per group of N visible GPUs
  (``$CUDA_VISIBLE_DEVICES`` if set, else ``nvidia-smi``). A task runs with
  ``CUDA_VISIBLE_DEVICES`` pinned to its slot's GPUs, so concurrent tasks never
  share a card.
- CPU tasks (``-g 0``): ``cpu_count // --cpus-per-task`` slots (all cores when
  ``--cpus-per-task`` is unset).

``--max-concurrent`` caps the slot count either way. The remaining scheduler flags
(``--time``, ``--mem``, ``--account``, ``--partitions``, ``--modal-gpu``) are ignored.

Unlike sbatch and Modal, submission blocks: ``sapia run`` returns once every task
has finished, and exits non-zero if any failed. Each task writes
``<log_dir>/<script>_<id>.out|.err|.exit`` like the Modal executor does.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import SubmitCtx, write_manifest

Slot = dict[str, str]  # env overrides a task runs with (e.g. its CUDA_VISIBLE_DEVICES)


def submit(ctx: SubmitCtx) -> None:
    write_manifest(ctx.manifest_base, ctx.rows)
    slots = resolve_slots(ctx)
    n_tasks = len(ctx.rows)
    print(f"Running {n_tasks} task(s) locally, {len(slots)} at a time")

    free: queue.Queue[Slot] = queue.Queue()
    for slot in slots:
        free.put(slot)

    def run_one(task_id: int) -> int:
        slot = free.get()
        try:
            started = time.monotonic()
            code = run_task(ctx, task_id, slot)
            print(
                f"task {task_id}/{n_tasks}: exit {code} ({time.monotonic() - started:.0f}s)"
            )
            return code
        finally:
            free.put(slot)

    with ThreadPoolExecutor(max_workers=len(slots)) as pool:
        codes = list(pool.map(run_one, range(1, n_tasks + 1)))

    failed = [i + 1 for i, c in enumerate(codes) if c != 0]
    if failed:
        raise RuntimeError(
            f"{len(failed)}/{n_tasks} task(s) failed: {', '.join(map(str, failed))}. "
            f"See {ctx.log_dir}/{ctx.script.stem}_<id>.err"
        )
    print(f"All {n_tasks} task(s) finished")


def run_task(ctx: SubmitCtx, task_id: int, slot: Slot) -> int:
    """Run one manifest line's script, logging to ``<log_dir>/<script>_<id>.*``."""
    prefix = ctx.log_dir / f"{ctx.script.stem}_{task_id}"
    env = {**os.environ, **ctx.task_env("local"), **slot, "SAPIA_TASK_ID": str(task_id)}
    code = 255
    try:
        with open(f"{prefix}.out", "w") as out, open(f"{prefix}.err", "w") as err:
            code = subprocess.run(
                ["bash", str(ctx.script), str(ctx.manifest_base), str(ctx.out_dir)],
                env=env,
                stdout=out,
                stderr=err,
                cwd=os.getcwd(),
            ).returncode
    finally:
        Path(f"{prefix}.exit").write_text(f"{code}\n")
    return code


def resolve_slots(ctx: SubmitCtx) -> list[Slot]:
    """The concurrent task slots this machine offers for the run's resource shape."""
    args = ctx.args
    if args.gpus_per_task > 0:
        gpus = visible_gpus()
        per = args.gpus_per_task
        if len(gpus) < per:
            raise RuntimeError(
                f"--gpus-per-task {per} but only {len(gpus)} GPU(s) visible "
                f"({', '.join(gpus) or 'none'}). Set CUDA_VISIBLE_DEVICES, or pass "
                f"-g 0 for a CPU-only run."
            )
        slots: list[Slot] = [
            {"CUDA_VISIBLE_DEVICES": ",".join(gpus[i : i + per])}
            for i in range(0, len(gpus) - per + 1, per)
        ]
    else:
        n_cpus = os.cpu_count() or 1
        slots = [{} for _ in range(max(1, n_cpus // (args.cpus_per_task or 1)))]
    return slots[: max(1, args.max_concurrent)]


def visible_gpus() -> list[str]:
    """GPU ids this process may use: ``$CUDA_VISIBLE_DEVICES`` if set (empty means
    none), else every GPU ``nvidia-smi`` lists, else none."""
    env = os.environ.get("CUDA_VISIBLE_DEVICES")
    if env is not None:
        return [g.strip() for g in env.split(",") if g.strip()]
    if shutil.which("nvidia-smi") is None:
        return []
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
