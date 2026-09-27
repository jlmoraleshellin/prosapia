# Running a tool

`sapia run` is the submit phase: it turns a table into a SLURM array job. Every tool inherits the **same base flags** from the shared driver (`base_sbatch`) and may add its **own flags** for tool-specific parameters on top.

This page is the reference for the base set and, importantly, how it maps to (and departs from) plain SLURM.

## The shape of a run

```bash
# submit the array
sapia run     <tool> <run_dir> [-t <table>] [flags]  
# read results into the output table
sapia collect <tool> <run_dir> -t <table>            
```

A run does three things: it **resolves the output table** (the source table for an `update` tool, or a freshly reserved child/root for a `create` tool), builds a **manifest** — one line per *ready* design — and hands it to an **executor** that runs the tool's `.sh` task script once per manifest line: a **SLURM array** (default) or **Modal** containers (`--executor modal`). [`sapia collect`](collecting-a-tool.md) then closes the cycle. 

See [the two-phase execution model](architecture.md#the-two-phase-execution-model) for the full flow.

`--help` on any tool lists its exact flags:

```bash
sapia run <tool> --help
```

## Selecting what runs

These flags decide *which* designs are submitted and where their output lands.

| Flag | Default | Meaning |
| --- | --- | --- |
| `run_dir` (positional) | — | The workflow directory, minted by `sapia new_run`. |
| `-t`, `--table` | — | Source table in `run_dir` (name, no extension). **Required** for `update` tools; optional for `create` — omit it to start a fresh root lineage. |
| `-i`, `--input-column` | tool's `default_input_column` | Which table column feeds the tool (e.g. `pdb_path`). |
| `-l`, `--dir-label` | `""` | Suffix for the output dir, to run same-tool variants side by side (e.g. different seeds). Produces the leaf `<tool>_<dir_label>` and the dir `run_dir/<table>/<leaf>/`. See [Using labels](using-labels.md). |
| `--table-label` | `""` | **`create` tools only.** Labels the child table this run reserves (append rule: `table<gen>_<parent_label>_<table_label>`). Use it to disambiguate a fork. See [Using labels](using-labels.md). |
| `-f`, `--filter` | none | Path to a Python module exposing `apply_filter(df) -> df`, applied to the source frame *before* the manifest is built. See [Writing a filter function](writing-a-filter-function.md). |
| `--force` | off | Re-submit designs this tool already finished (skips the resume filter). |

## Choosing an executor

| Flag | Default | Meaning |
| --- | --- | --- |
| `-e`, `--executor` | `$SAPIA_EXECUTOR`, else `slurm` | Which scheduler runs the tasks: `slurm` or `modal`. The manifest and the task script are the same for both. |
| `-s`, `--script` | tool's `default_script` | The `.sh` task script each task runs (`<script> <manifest> <out_dir>`). Override to point at a customized script. |
| `--modal-gpu` | tool's `RESOURCES["gpu"]` | **Modal only.** GPU type, e.g. `A100`, `H100`. |

Every task gets its 1-based manifest index as `SAPIA_TASK_ID` (plus `SAPIA_PRELUDE`, `SAPIA_TOOL_DIR`, `SAPIA_TOOL` and `SAPIA_SCHEDULER`), so the same script runs unchanged under either executor. See [Running on Modal](#running-on-modal).

### The ready set

You never filter or resume by hand. The driver submits the **ready** designs: rows with a present `--input-column`, minus those this tool already completed (`<leaf>_status == "OK"`) unless `--force`. The already-OK skip is the framework's resume-on-rerun — rerun the same command after a partial failure and only the unfinished designs go back out. (The skip fires for `update` tools, whose status column lives in the same table; for `create` tools the column lives in the child table, so every ready design is submitted.)

## Scheduling flags → SLURM

These map onto the `sbatch` invocation the driver builds. It emits only the flags below; everything else about the job (see [the next section](#cli-flags-vs-sbatch-directives)) comes from the tool's own `.sh` task script.

| Flag | Default | Emitted as |
| --- | --- | --- |
| `-a`, `--account` | unset | `--account=<value>` (omitted when unset). |
| `-C`, `--max-concurrent` | `40` | The throttle in `--array=1-N%<value>`. **Ignored with `--partitions`** — there each partition's cap is derived from `--max-gpu-fraction` instead (see below). |
| `-g`, `--gpus-per-task` | `1` | `--gres=gpu:<value>`. Set `0` for CPU-only tasks (no `--gres` emitted). |
| `-c`, `--cpus-per-task` | unset | `--cpus-per-task=<value>` (omitted when unset). Overrides the `#SBATCH --cpus-per-task` in the tool's `.sh` task script. |
| `-t`, `--time` | unset | `--time=<value>`, e.g. `04:00:00` (omitted when unset). Overrides the `#SBATCH --time` in the tool's `.sh` task script. |
| `--mem` | unset | `--mem=<value>`, e.g. `32G` (omitted when unset). Overrides the `#SBATCH --mem` in the tool's `.sh` task script. |
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
  --output=<out_dir>/<script>_logs/%A_%a.out \
  --error=<out_dir>/<script>_logs/%A_%a.err \
  <script> <manifest> <out_dir>
```

## What the driver decides for you

Several things are **not** 1:1 SLURM passthroughs — the driver computes them:

- **Array size is derived, never passed.** `N` in `--array=1-N` is the number of ready designs. You size a run by choosing its inputs, not by writing an array range.
- **Concurrency throttle.** `--max-concurrent` becomes the `%N` in the array spec, capping how many tasks run at once.
- **Auto-chunking.** If the ready count exceeds  `SLURM_MAX_ARRAY_SIZE` (env, default `1000`), the driver splits the manifest into several array jobs automatically.
- **Multi-partition fan-out.** With `--partitions`, the driver submits **one array per partition**, splitting the designs across them. Here the concurrency cap is computed per partition as `max_gpu_fraction × GPUs ÷ gpus_per_task`. This **replaces `--max-concurrent`**, which is not applied in partition mode. If you omit a partition's GPU count it is auto-detected via `sinfo`. Each partition's share is still chunked to respect `SLURM_MAX_ARRAY_SIZE`.
- **Task hand-off.** Each array task receives two positional args (the `manifest` and the `out_dir`) and the driver injects `SAPIA_PRELUDE` into the environment so the `.sh` task script prelude can resolve this task's manifest line (from `SLURM_ARRAY_TASK_ID`).

> [!WARNING]
> **`--partitions` is GPU-only for now.** The per-partition concurrency cap is derived entirely from GPU count (`max_gpu_fraction × GPUs ÷ gpus_per_task`), so choosing partitions only makes sense for GPU jobs. A CPU-only run (`--gpus-per-task 0`) has no GPU count to cap against. For CPU jobs, set `--gpus-per-task 0`, control concurrency with `-C/--max-concurrent` instead and let SLURM allocate it in the available partitions. This will be fixed in the future.

## Logs

You don't have to set up logging, the driver does it. It creates a log folder **next to the run's output**, at `<out_dir>/<script>_logs/`, and points SLURM's `--output`/`--error` there. Each array task writes two files:

```
run_dir/<table>/<leaf>/<script>_logs/
├── <jobid>_<taskid>.out   # stdout  (%A = array job id, %a = task index)
└── <jobid>_<taskid>.err   # stderr
```

`<script>` is the `.sh` task script stem (so a custom `--script` names its own log folder). The submit command prints both the output dir and the log dir, so you always see where a run's logs will land:

```
Submitting 128 designs
Output:  run_dir/table1_seqs/proteinmpnn
Logs:    run_dir/table1_seqs/proteinmpnn/proteinmpnn_logs
```

When a task fails, its `.err` file under that folder is the first place to look.

## CLI flags vs. `#SBATCH` directives

Every tool's `.sh` task script sets its own **baseline resources** as `#SBATCH` lines: wall time, memory, `cpus-per-task`, job name. The base flags above then let you **override** three of them per run: `-t/--time`, `--mem`, `-c/--cpus-per-task` (a flag passed on the `sbatch` command line wins over the matching `#SBATCH` directive in the script). 

Only the **job name** stays script-only — it is not a CLI flag, so it is always whatever the tool's `.sh` task script declares.

To change a tool's *baseline* resources permanently, edit (or [fork](writing-a-tool.md#customizing-bundled-tools)) its `.sh` task script. See [Writing a task script](writing-a-tool.md#writing-a-task-script).

## Running on Modal

`--executor modal` runs each manifest line in its own Modal container, using the tool's image instead of an activation script:

- **Image.** The tool ships a `modal_image.py` next to its task script defining `image() -> modal.Image`, and optionally `RESOURCES` (`gpu`, `cpu`, `memory`, `timeout`, in the same formats as the SLURM flags) and `volumes() -> dict[str, modal.Volume]` for weights or databases. Tools without one can't run on Modal yet. The task script, its sibling files and the prelude are added to the image at their local paths.
- **Storage.** Runs live on a Modal Volume: set `SAPIA_MODAL_RUNS_VOLUME` (volume name) and `SAPIA_MODAL_RUNS_MOUNT` (the absolute path it is mounted at) in `.env`. The `run_dir` must be under that mount so manifest and table paths resolve inside the containers.
- **Resources.** `-g/--gpus-per-task`, `-c/--cpus-per-task`, `--mem` and `-T/--time` override the tool's `RESOURCES`; `--modal-gpu` picks the GPU type. `-C/--max-concurrent` caps the number of running containers. The SLURM-only flags (`--account`, `--partitions`, `--max-gpu-fraction`) are ignored.
- **Submission** is detached, like `sbatch`: `sapia run` returns once the tasks are queued. Each task writes `<out_dir>/<script>_logs/<script>_<task_id>.{out,err}`, and `sapia collect` works unchanged.
- **Serialization.** The task function is pickled on the client, so the image's Python version must match the one running `sapia`. Install the SDK with `prosapia[modal]`.

## Tool-specific flags

The flags above are the **base set** shared by every tool. A tool can also declare its own flags for its parameters — a diffusion count, a sampling temperature, a number of sequences per backbone — which appear alongside the base ones on that tool's `sapia run`. They are authored via the tool's optional `add_run_args_fn` (see [Writing a tool](writing-a-tool.md)). Because the set varies per tool, the authoritative list for any given tool is always:

```bash
sapia run <tool> --help
```

## Environment knobs

| Variable | Default | Effect |
| --- | --- | --- |
| `SLURM_MAX_ARRAY_SIZE` | `1000` | Max tasks per array job before the driver chunks a run into multiple submissions. |
