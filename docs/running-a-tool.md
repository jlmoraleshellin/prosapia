# Running a tool

`sapia run` is the submit phase: it turns a table into one task per ready design and hands those tasks to a scheduler. Every tool inherits the **same base flags** from the shared driver (`base_run`) and may add its **own flags** for tool-specific parameters on top.

This page covers what every run shares: selecting what runs, the executors and the task contract. The scheduler-specific details live in their own pages:

- **[Running on SLURM](running-on-slurm.md)**: `sbatch` arrays on an HPC cluster, the default.
- **[Running on Modal](running-on-modal.md)**: Modal containers, with runs stored on a Modal Volume.
- **[Running locally](running-locally.md)**: subprocesses on this machine, with no scheduler in between.

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
| `-l`, `--dir-label` | `""` | Suffix for the output dir, to run same-tool variants side by side (e.g. different seeds). Produces the leaf `<tool>_<dir_label>` and the dir `run_dir/<table>/<leaf>/`; each submission writes into its own `<leaf>/.submissions/<NN>/`. See [Using labels](using-labels.md). |
| `--table-label` | `""` | **`create` tools only.** Labels the child table this run reserves (append rule: `table<gen>_<parent_label>_<table_label>`). Use it to disambiguate a fork. See [Using labels](using-labels.md). |
| `-f`, `--filter` | none | Path to a Python module exposing `apply_filter(df) -> df`, applied to the source frame *before* the manifest is built. See [Writing a filter function](writing-a-filter-function.md). |
| `-w`, `--where` | none | `COL=VALUE`: keep only rows whose column equals the value (string compare). Repeatable, applied after `--filter`. Typical use: `-w merge_source=table1_a` to run a tool with fork-specific arguments on a merged table (see [Using labels](using-labels.md#merging-sibling-tables-sapia-merge)). |
| `--force` | off | Re-submit designs this tool already finished (skips the resume filter). |

### The ready set

You never filter or resume by hand. The driver submits the **ready** designs: rows with a present `--input-column`, minus those this tool already completed (`<leaf>_status == "OK"`), unless you pass `--force`.

The already-OK skip is the framework's resume-on-rerun: rerun the same command after a partial failure and only the unfinished designs go back out. For an `update` tool a row is done when its own `<leaf>_status` is `OK`. For a `create` tool the status lives on the child table, so a source row is done once any child row naming it as `parent_name` is `OK`; a source row whose children all failed, or that never produced one, goes back out. Collect first, then rerun: the skip reads the table, not the disk.

## Choosing an executor

The manifest and the task script are the same for every scheduler. An executor only decides how the manifest lines are scheduled and launched.

| Flag | Default | Meaning |
| --- | --- | --- |
| `-e`, `--executor` | `$SAPIA_EXECUTOR`, else `slurm` | Who runs the tasks: `slurm`, `modal` or `local`. |
| `-s`, `--script` | tool's `default_script` | The `.sh` task script each task runs (`<script> <manifest> <out_dir>`). Override to point at a customized script. |

How the two compare:

| | SLURM | Modal | Local |
| --- | --- | --- | --- |
| Where `sapia` runs | a login node | the `sapia modal-shell` workstation | the machine doing the work |
| Where runs are stored | the cluster filesystem | the runs Volume, at `/runs` | this machine's filesystem |
| Tool environment | your activation script (`sapia_activate`) | the tool's `modal_image.py` | your activation script (`sapia_activate`) |
| One task is | an array task | a container | a subprocess |
| Baseline resources | `#SBATCH` lines in the `.sh` | `RESOURCES` in `modal_image.py` | none; limits are not enforced |
| Concurrency is | the array throttle | the container cap | the number of GPU/CPU slots |
| `sapia run` returns | once queued | once queued | once every task has finished |
| Task status | `squeue` / `sacct` | `.exit` files and the Modal app | the exit codes printed by the run |

### Resource flags

These flags exist under both executors. Each executor translates them into its own terms:

| Flag | Default | Meaning |
| --- | --- | --- |
| `-C`, `--max-concurrent` | `40` | Maximum number of tasks running at once (a cap only: `local` cannot exceed its slot count). |
| `-g`, `--gpus-per-task` | `1` | GPUs per task; `0` for CPU-only tasks. |
| `-c`, `--cpus-per-task` | unset | CPUs per task. Overrides the tool's baseline. |
| `-T`, `--time` | unset | Wall time per task, e.g. `04:00:00`. Overrides the tool's baseline. |
| `--mem` | unset | Memory per task, e.g. `32G`. Overrides the tool's baseline. |

Flags that belong to one scheduler (`--account`, `--partitions` and `--max-gpu-fraction` for SLURM, `--modal-gpu` for Modal) are documented on its page and ignored by the others. The `local` executor enforces no limits at all, so it uses only `-g` and `-c`, to size its slots.

## The task contract

Every task runs `<script> <manifest> <out_dir>` with these variables set:

| Variable | Meaning |
| --- | --- |
| `SAPIA_TASK_ID` | This task's 1-based manifest line. |
| `SAPIA_SCHEDULER` | `slurm`, `modal` or `local`. |
| `SAPIA_PRELUDE` | The shared prelude the `.sh` sources; it resolves `SAPIA_LINE` and provides `sapia_activate`. |
| `SAPIA_TOOL_DIR`, `SAPIA_TOOL` | The tool's directory and name. |

So the same script runs unchanged under every executor. See [Writing a task script](writing-a-tool.md#writing-a-task-script).

## Where to run `sapia` from

Stored paths are relative to where `sapia` ran, and tasks start in that same directory: the submit directory on SLURM and `local`, `/runs` on Modal. Always run `sapia` from that root and pass the run_dir path that `new_run` prints. Don't `cd` into a run_dir: a table collected from inside one points at files no downstream task can find.

## Logs

Every submission gets its own output dir, `<leaf>/.submissions/<NN>/`, so a resubmit never overwrites or mixes with a previous run's scratch and outputs; collect reads them newest first. The log folder stays at the leaf, `<leaf>/<script>_logs/`, shared by all submissions. Both locations are printed on submit:

```
Submitting 128 designs
Output:  run_dir/table1_seqs/proteinmpnn/.submissions/01
Logs:    run_dir/table1_seqs/proteinmpnn/proteinmpnn_logs
```

`<script>` is the `.sh` task script stem, so a custom `--script` names its own log folder. The file names inside it depend on the executor. When a task fails, its `.err` file is the first place to look.

## Tool-specific flags

The flags above are the **base set** shared by every tool. A tool can also declare its own flags for its parameters, such as a diffusion count, a sampling temperature or a number of sequences per backbone. They appear alongside the base ones on that tool's `sapia run` and are authored via the tool's optional `add_run_args_fn` (see [Writing a tool](writing-a-tool.md)). Because the set varies per tool, the authoritative list for any given tool is always:

```bash
sapia run <tool> --help
```
