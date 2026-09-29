# Running a tool

`sapia run` is the submit phase: it turns a table into one task per ready design and hands those tasks to a scheduler. Every tool inherits the **same base flags** from the shared driver (`base_run`) and may add its **own flags** for tool-specific parameters on top.

This page covers what every run shares: selecting what runs, the executors and the task contract. The scheduler-specific details live in their own pages:

- **[Running on SLURM](running-on-slurm.md)**: `sbatch` arrays on an HPC cluster, the default.
- **[Running on Modal](running-on-modal.md)**: Modal containers, with runs stored on a Modal Volume.

## The shape of a run

```bash
# submit the tasks
sapia run     <tool> <run_dir> [-t <table>] [flags]
# read results into the output table
sapia collect <tool> <run_dir> -t <table>
```

A run does three things:
1. It **resolves the output table**: the source table for an `update` tool, or a freshly reserved child/root for a `create` tool.
2. It builds a **manifest**, with one line per *ready* design.
3. It hands the manifest to an **executor**, which runs the tool's `.sh` task script once per manifest line.

[`sapia collect`](collecting-a-tool.md) then closes the cycle. See [the two-phase execution model](architecture.md#the-two-phase-execution-model) for the full flow.

`--help` on any tool lists its exact flags:

```bash
sapia run <tool> --help
```

## Selecting what runs

These flags decide *which* designs are submitted and where their output lands. They behave the same under every executor.

| Flag | Default | Meaning |
| --- | --- | --- |
| `run_dir` (positional) | — | The workflow directory, minted by `sapia new_run`. |
| `-t`, `--table` | — | Source table in `run_dir` (name, no extension). **Required** for `update` tools; optional for `create`, where omitting it starts a fresh root lineage. |
| `-i`, `--input-column` | tool's `default_input_column` | Which table column feeds the tool (e.g. `pdb_path`). |
| `-l`, `--dir-label` | `""` | Suffix for the output dir, to run same-tool variants side by side (e.g. different seeds). Produces the leaf `<tool>_<dir_label>` and the dir `run_dir/<table>/<leaf>/`. See [Using labels](using-labels.md). |
| `--table-label` | `""` | **`create` tools only.** Labels the child table this run reserves (append rule: `table<gen>_<parent_label>_<table_label>`). Use it to disambiguate a fork. See [Using labels](using-labels.md). |
| `-f`, `--filter` | none | Path to a Python module exposing `apply_filter(df) -> df`, applied to the source frame *before* the manifest is built. See [Writing a filter function](writing-a-filter-function.md). |
| `--force` | off | Re-submit designs this tool already finished (skips the resume filter). |

### The ready set

You never filter or resume by hand. The driver submits the **ready** designs: rows with a present `--input-column`, minus those this tool already completed (`<leaf>_status == "OK"`), unless you pass `--force`.

The already-OK skip is the framework's resume-on-rerun: rerun the same command after a partial failure and only the unfinished designs go back out. The skip only fires for `update` tools, whose status column lives in the same table. For `create` tools the status column lives in the child table, so every ready design is submitted.

## Choosing an executor

The manifest and the task script are the same for every scheduler. An executor only decides how the manifest lines are scheduled and launched.

| Flag | Default | Meaning |
| --- | --- | --- |
| `-e`, `--executor` | `$SAPIA_EXECUTOR`, else `slurm` | Which scheduler runs the tasks: `slurm` or `modal`. |
| `-s`, `--script` | tool's `default_script` | The `.sh` task script each task runs (`<script> <manifest> <out_dir>`). Override to point at a customized script. |

How the two compare:

| | SLURM | Modal |
| --- | --- | --- |
| Where `sapia` runs | a login node | the `sapia modal-shell` workstation |
| Where runs are stored | the cluster filesystem | the runs Volume, at `/runs` |
| Tool environment | your activation script (`sapia_activate`) | the tool's `modal_image.py` |
| One task is | an array task | a container |
| Baseline resources | `#SBATCH` lines in the `.sh` | `RESOURCES` in `modal_image.py` |
| Task status | `squeue` / `sacct` | `.exit` files and the Modal app |

### Resource flags

These flags exist under both executors. Each executor translates them into its own terms:

| Flag | Default | Meaning |
| --- | --- | --- |
| `-C`, `--max-concurrent` | `40` | Maximum number of tasks running at once. |
| `-g`, `--gpus-per-task` | `1` | GPUs per task; `0` for CPU-only tasks. |
| `-c`, `--cpus-per-task` | unset | CPUs per task. Overrides the tool's baseline. |
| `-T`, `--time` | unset | Wall time per task, e.g. `04:00:00`. Overrides the tool's baseline. |
| `--mem` | unset | Memory per task, e.g. `32G`. Overrides the tool's baseline. |

Flags that belong to one scheduler (`--account`, `--partitions` and `--max-gpu-fraction` for SLURM, `--modal-gpu` for Modal) are documented on its page and ignored by the other.

## The task contract

Every task runs `<script> <manifest> <out_dir>` with these variables set:

| Variable | Meaning |
| --- | --- |
| `SAPIA_TASK_ID` | This task's 1-based manifest line. |
| `SAPIA_SCHEDULER` | `slurm` or `modal`. |
| `SAPIA_PRELUDE` | The shared prelude the `.sh` sources; it resolves `SAPIA_LINE` and provides `sapia_activate`. |
| `SAPIA_TOOL_DIR`, `SAPIA_TOOL` | The tool's directory and name. |

So the same script runs unchanged under either executor. See [Writing a task script](writing-a-tool.md#writing-a-task-script).

## Where to run `sapia` from

Stored paths are relative to where `sapia` ran, and tasks start in that same directory: the submit directory on SLURM, `/runs` on Modal. Always run `sapia` from that root and pass the run_dir path that `new_run` prints. Don't `cd` into a run_dir: a table collected from inside one points at files no downstream task can find.

## Logs

The driver creates a log folder next to the run's output, at `<out_dir>/<script>_logs/`, and prints both locations on submit:

```
Submitting 128 designs
Output:  run_dir/table1_seqs/proteinmpnn
Logs:    run_dir/table1_seqs/proteinmpnn/proteinmpnn_logs
```

`<script>` is the `.sh` task script stem, so a custom `--script` names its own log folder. The file names inside it depend on the executor. When a task fails, its `.err` file is the first place to look.

## Tool-specific flags

The flags above are the **base set** shared by every tool. A tool can also declare its own flags for its parameters, such as a diffusion count, a sampling temperature or a number of sequences per backbone. They appear alongside the base ones on that tool's `sapia run` and are authored via the tool's optional `add_run_args_fn` (see [Writing a tool](writing-a-tool.md)). Because the set varies per tool, the authoritative list for any given tool is always:

```bash
sapia run <tool> --help
```
