# Running locally

`--executor local` runs the tasks on the machine `sapia` is on: a workstation, or an interactive HPC node you already hold. Nothing is submitted to a scheduler. The driver runs the tool's `.sh` task script as a subprocess, a few tasks at a time, and `sapia run` returns only once they have all finished. For what every run shares (selecting designs, the task contract, logs), see [Running a tool](running-a-tool.md).

Each task activates its tool through the activation script named in your `.env` (`sapia_activate SAPIA_ACTIVATE_<TOOL>`), exactly as on SLURM. See [Configuration](configuration.md).

```bash
sapia run proteinmpnn my_run -t table1 --executor local
```

Set `SAPIA_EXECUTOR=local` in your `.env` to make it the default for every run.

## Concurrency: slots

The executor builds a fixed set of **slots** and keeps one task in each, starting the next task as soon as a slot frees up. How many slots exist depends on the run's resource shape:

| Run | Slots | Each task gets |
| --- | --- | --- |
| GPU (`-g N`, default `1`) | one per group of `N` visible GPUs | `CUDA_VISIBLE_DEVICES` pinned to that slot's GPUs |
| CPU-only (`-g 0`) | `cpu_count ÷ --cpus-per-task` (all cores when unset) | the machine's environment, unchanged |

`-C/--max-concurrent` caps the slot count in both cases, so it is the one flag that always lowers the load. It cannot raise it: the GPU count is the ceiling for a GPU run.

Visible GPUs come from `CUDA_VISIBLE_DEVICES` if it is set, otherwise from `nvidia-smi`. Because each task's `CUDA_VISIBLE_DEVICES` is rewritten to its own slot, two tasks never share a card. A GPU run on a machine with fewer GPUs than `--gpus-per-task` fails immediately rather than oversubscribing.

```bash
# 4 GPUs, one per task → 4 tasks at a time
sapia run rfdiffusion my_run --executor local

# the same machine, but keep two cards free
CUDA_VISIBLE_DEVICES=0,1 sapia run rfdiffusion my_run --executor local

# CPU-only tool, 4 cores each on a 32-core box → 8 tasks at a time
sapia run pyrosetta my_run -t table1 --executor local -g 0 -c 4
```

## What is ignored

The local executor schedules nothing, so it enforces no resource limits. `--time`, `--mem`, `--account`, `--partitions`, `--max-gpu-fraction` and `--modal-gpu` are accepted and ignored. A task that would have been killed by a SLURM wall-time or memory limit simply keeps running, or is killed by the kernel's OOM killer.

The tool's `#SBATCH` lines are likewise inert: they are comments in the `.sh`, read only by `sbatch`. Only `--gpus-per-task` and `--cpus-per-task` change anything here, and only by setting the slot count.

## Submission, logs and task status

Unlike `sbatch` and Modal, the run is **blocking and in the foreground**. Each task prints its exit code and wall time as it finishes, and `sapia run` exits non-zero if any task failed, naming the failed task ids. Interrupting with `Ctrl-C` stops the run.

The log folder holds the same files the Modal executor writes:

```
run_dir/<table>/<leaf>/<script>_logs/
├── <script>_<task_id>.out    # stdout
├── <script>_<task_id>.err    # stderr
└── <script>_<task_id>.exit   # exit code; 255 if the task could not be started
```

Every task writes its `.exit` file, whatever happens. Because the run blocks, there is no "still running" state to diagnose after the fact: when `sapia run` returns, the manifest is done. A failed task's `.err` file is the first place to look. `sapia collect` then works unchanged.

## When to use it

- **Developing a tool.** The fastest loop for a new `.sh` or `build_manifest_fn` is a one-row manifest run in the foreground, where the failure prints as it happens.
- **A workstation with GPUs**, where a scheduler would only add queueing.
- **An interactive allocation** (`salloc`, `srun --pty`): the node is already yours, so running the manifest inside it beats submitting a nested array job.

For a shared cluster, keep using [SLURM](running-on-slurm.md): it is the one that queues, enforces limits and shares the machine fairly.
