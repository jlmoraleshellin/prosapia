# Running on SLURM

`--executor slurm` (the default) submits a run as `sbatch` array jobs, one array task per manifest line. This page covers how `sapia run` maps to, and departs from, plain SLURM. For what every run shares (selecting designs, the task contract, logs), see [Running a tool](running-a-tool.md).

Each task activates its tool through the activation script named in your `.env` (`sapia_activate SAPIA_ACTIVATE_<TOOL>`). See [Configuration](configuration.md).

## Scheduling flags → `sbatch`

The driver emits only the flags below. Everything else about the job comes from the tool's own `.sh` task script (see [CLI flags vs. `#SBATCH` directives](#cli-flags-vs-sbatch-directives)).

| Flag | Default | Emitted as |
| --- | --- | --- |
| `-a`, `--account` | unset | `--account=<value>` (omitted when unset). |
| `-C`, `--max-concurrent` | `40` | The throttle in `--array=1-N%<value>`. **Ignored with `--partitions`**: there each partition's cap is derived from `--max-gpu-fraction` instead (see below). |
| `-g`, `--gpus-per-task` | `1` | `--gres=gpu:<value>`. Set `0` for CPU-only tasks (no `--gres` emitted). |
| `-c`, `--cpus-per-task` | unset | `--cpus-per-task=<value>` (omitted when unset). |
| `-T`, `--time` | unset | `--time=<value>`, e.g. `04:00:00` (omitted when unset). |
| `--mem` | unset | `--mem=<value>`, e.g. `32G` (omitted when unset). |
| `-p`, `--partitions` | none | Comma-separated partitions with optional GPU counts, e.g. `ampere_gpu:40,hopper_gpu:80`. Triggers multi-partition fan-out (below). |
| `--max-gpu-fraction` | `0.5` | Fraction of each partition's GPUs to use as the concurrency cap. Only used with `--partitions`. |

The generated command looks like this (empty flags are dropped):

```bash
sbatch \
  --account=<account> \
  --array=1-<N>%<max_concurrent> \
  --partition=<partition> \
  --gres=gpu:<gpus_per_task> \
  --cpus-per-task=<cpus_per_task> \
  --time=<time> \
  --mem=<mem> \
  --output=<out_dir>/<script>_logs/<script>_%A_%a.out \
  --error=<out_dir>/<script>_logs/<script>_%A_%a.err \
  <script> <manifest> <out_dir>
```

## What the driver decides for you

Several things are **not** 1:1 SLURM passthroughs. The driver computes them:

- **Array size is derived, never passed.** `N` in `--array=1-N` is the number of ready designs. You size a run by choosing its inputs, not by writing an array range.
- **Concurrency throttle.** `--max-concurrent` becomes the `%N` in the array spec, capping how many tasks run at once.
- **Auto-chunking.** If the ready count exceeds `SLURM_MAX_ARRAY_SIZE` (env, default `1000`), the driver splits the manifest into several array jobs automatically.
- **Multi-partition fan-out.** With `--partitions`, the driver submits **one array per partition**, splitting the designs across them.
  - The concurrency cap is computed per partition as `max_gpu_fraction × GPUs ÷ gpus_per_task`. This **replaces `--max-concurrent`**, which is not applied in partition mode.
  - If you omit a partition's GPU count, it is auto-detected via `sinfo`.
  - Each partition's share is still chunked to respect `SLURM_MAX_ARRAY_SIZE`.
- **Task hand-off.** Each array task receives the `manifest` and the `out_dir` as positional args. The driver exports `SAPIA_SCHEDULER=slurm` and the rest of the [task contract](running-a-tool.md#the-task-contract), and the prelude takes the task's line from `SLURM_ARRAY_TASK_ID`.

> [!WARNING]
> **`--partitions` is GPU-only for now.** The per-partition concurrency cap is derived entirely from GPU count (`max_gpu_fraction × GPUs ÷ gpus_per_task`), so choosing partitions only makes sense for GPU jobs. A CPU-only run (`--gpus-per-task 0`) has no GPU count to cap against. For CPU jobs, set `--gpus-per-task 0`, control concurrency with `-C/--max-concurrent` and let SLURM allocate it in the available partitions. This will be fixed in the future.

## Logs

SLURM's `--output`/`--error` point at the run's log folder. Each array task writes two files:

```
run_dir/<table>/<leaf>/<script>_logs/
├── <script>_<jobid>_<taskid>.out   # stdout  (%A = array job id, %a = task index)
└── <script>_<jobid>_<taskid>.err   # stderr
```

Track progress with `squeue` / `sacct` using the job IDs `sbatch` prints.

## CLI flags vs. `#SBATCH` directives

Every tool's `.sh` task script sets its own **baseline resources** as `#SBATCH` lines: wall time, memory, `cpus-per-task` and job name. The [resource flags](running-a-tool.md#resource-flags) `-T/--time`, `--mem` and `-c/--cpus-per-task` **override** three of them per run, because a flag passed on the `sbatch` command line wins over the matching `#SBATCH` directive in the script.

Only the **job name** stays script-only. It is not a CLI flag, so it is always whatever the tool's `.sh` task script declares.

To change a tool's *baseline* resources permanently, edit (or [fork](writing-a-tool.md#customizing-bundled-tools)) its `.sh` task script. See [Writing a task script](writing-a-tool.md#writing-a-task-script).

## Environment knobs

| Variable | Default | Effect |
| --- | --- | --- |
| `SLURM_MAX_ARRAY_SIZE` | `1000` | Max tasks per array job before the driver chunks a run into multiple submissions. |
