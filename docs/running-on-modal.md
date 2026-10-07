# Running on Modal

`--executor modal` runs each manifest line in its own Modal container, using the tool's image instead of an activation script. For what every run shares (selecting designs, the task contract, logs), see [Running a tool](running-a-tool.md).

## The workstation

On Modal, run_dirs live only on a Modal Volume, mounted at `/runs`. `sapia` runs next to it in a small container, the **workstation**, instead of on your machine, so nothing is stored locally.

Install the SDK with `prosapia[modal]`, set `SAPIA_MODAL_RUNS_VOLUME` (the Volume name) in your local `.env`, then open the workstation from the project directory:

```bash
modal volume put sapia-runs inputs/ /inputs        # upload inputs once (PDBs, filters, YAMLs)
sapia modal-shell                                  # interactive shell; cwd is /runs
sapia modal-shell --cmd "sapia new_run --label x"  # or one command, then exit
```

- **Usage.** Inside the workstation, `sapia` works as usual and `run` defaults to `--executor modal`. Relative paths resolve against `/runs`, so run `sapia` from there (see [Where to run `sapia` from](running-a-tool.md#where-to-run-sapia-from)).
- **`--cmd`.** It takes any shell command, quotes included, and exits with that command's exit code, so an agent can drive prosapia one command at a time.
- **Browsing results.** Use the Modal dashboard or `modal volume ls|get`.
- **Size and lifetime.** The workstation is sized at 0.25 CPU / 1 GiB (`SAPIA_MODAL_SHELL_CPU`, `SAPIA_MODAL_SHELL_MEMORY`) and exits with the shell.
- **Contents.** Its image holds prosapia's dependencies, your prosapia source and your `$PROSAPIA_TOOLS_DIR`. It receives your local `.env`, which it forwards to every task.
- **Credentials.** The workstation launches task containers with its own credentials; no Modal token is needed.

## Tool images

A tool runs on Modal once it ships a `modal_image.py` next to its task script:

```python
def image() -> modal.Image: ...                    # required
RESOURCES = {"gpu": "A100", "cpu": 8, "memory": "32G", "timeout": "02:00:00"}  # optional
def volumes() -> dict[str, modal.Volume]: ...      # optional: weights, databases, caches
```

Tools without one can't run on Modal yet. The task script, its sibling files and the prelude are added to the image at the same paths they have in the workstation.

**Python versions.** Each tool image picks its own Python; it doesn't have to match the workstation's. Modal mounts a small stdlib-only entrypoint (`executors/sapia_modal_task.py`) into the image and imports it, so the image's Python only needs to be one Modal supports. An image with no Python of its own (e.g. `Image.from_registry`) gets one with `add_python=...`.

## Resources

The [resource flags](running-a-tool.md#resource-flags) `-g/--gpus-per-task`, `-c/--cpus-per-task`, `--mem` and `-T/--time` override the tool's `RESOURCES`, and `-C/--max-concurrent` caps the number of running containers. The SLURM-only flags (`--account`, `--partitions`, `--max-gpu-fraction`) are ignored.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--modal-gpu` | tool's `RESOURCES["gpu"]` | GPU type, e.g. `A100`, `H100`. With `-g N > 1` it becomes `TYPE:N`. |

## Storage

Every container, the workstation and each task, mounts the runs Volume at `/runs` and starts there, so the `run_dir` must be under `/runs`.

The Volume is created as a v2 Volume, which allows concurrent commits from many tasks. Keep in mind its limit of 262,144 files per directory.

Mounts commit in the background, so a file written at submit time can still be in flight when a task starts. The driver pushes the manifest through the Volume API before fanning out; a tool that writes its own side files (sub-manifests, shard inputs, staged structures) does the same by passing them to [`ctx.publish`](writing-a-build-manifest-function.md#side-files-ctxpublish).

## Submission, logs and task status

Submission is detached, like `sbatch`: `sapia run` returns once the tasks are queued. The run's log folder holds:

```
run_dir/<table>/<leaf>/<script>_logs/
├── <script>_<task_id>.out    # stdout
├── <script>_<task_id>.err    # stderr
├── <script>_<task_id>.exit   # exit code; 255 if the wrapper itself failed
└── <script>_modal.json       # {"app_id": ..., "n_tasks": ...}
```

Every task writes its `.exit` file, even when it fails. Before collecting, read the run's state from these files:

| State | How to tell |
| --- | --- |
| done | `n_tasks` `.exit` files, all `0` |
| failed | an `.exit` that isn't `0`; read the matching `.err` |
| running | `.exit` files missing while the app runs |
| killed | `.exit` files missing after the app stopped (timeout/OOM); see `modal app logs <app_id>` |

`sapia collect` then works unchanged from the workstation.

## Environment knobs

| Variable | Default | Effect |
| --- | --- | --- |
| `SAPIA_MODAL_RUNS_VOLUME` | — | **Required.** Name of the runs Volume, created on first use. |
| `SAPIA_MODAL_SHELL_CPU` | `0.25` | Workstation CPUs. |
| `SAPIA_MODAL_SHELL_MEMORY` | `1024` | Workstation memory, in MiB. |
| `SAPIA_MODAL_VOLUME_*`, `SAPIA_MODAL_AF3_IMAGE` | per tool | Weight, database and cache Volumes used by the bundled tools' images (see `env.example`). |
