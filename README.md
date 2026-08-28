# prosapia

A protein-design pipeline that gives easy, uniform access to many protein-design
tools (RFdiffusion, ProteinMPNN, ColabFold, Boltz, ...) in an HPC / SLURM
environment. The `sapia` CLI wraps each tool as a two-phase step against a shared
run directory, so heterogeneous tools compose into one lineage-tracked workflow.

## Concepts

- **run_dir** — the container a workflow lives in. It holds the workflow's
  databases (`*.tsv` + `_registry.tsv`) and each tool's nested outputs
  (`run_dir/<db>/<tool>/`). Create one first; tools operate inside it, they never
  mint one.
- **tool** — a thin, self-describing unit: metadata + two hooks
  (`build_manifest_fn`, `collect_fn`) + a `.sbatch` script. The shared drivers own
  the flow; the hooks fill the tool-specific parts.
- **two phases** — `run` submits a SLURM array (builds a manifest, submits the
  `.sbatch`); `collect` reads the on-disk outputs back into the database.

```bash
sapia init                              # one-time: shell tab-completion
RUN_DIR=$(sapia new_run --label demo)   # create a run_dir (prints its path)
sapia run     rfdiffusion "$RUN_DIR" ...   # run_dir is a positional arg
sapia collect rfdiffusion "$RUN_DIR" -d <db> ...
```

## Customizing tools

The bundled tools are intentionally general and may not fit every workflow. There
are three ways to adapt them, from lightest to heaviest.

### 1. Reuse a bundled tool, override just what you need

`Tool` is a frozen dataclass; `get_builtin` fetches a bundled one and
`with_overrides` returns a copy with some fields swapped. In your own tool's
`spec.py`, reuse everything and replace only the hook that differs:

```python
from prosapia.core import get_builtin
from .my_collect import my_collect_fn

TOOL = get_builtin("rfdiffusion").with_overrides(collect_fn=my_collect_fn)
```

### 2. Fork a whole tool

To start from a working copy and edit freely:

```bash
sapia fork-tool rfdiffusion            # -> ./tools/rfdiffusion/
sapia fork-tool rfdiffusion my_rfdiff  # -> ./tools/my_rfdiff/
```

Then edit the copy's `spec.py` / `run_*` / `collect_*`.

### 3. Write a tool from scratch

Add a folder with a `spec.py` exporting `TOOL = Tool(...)`, a `run_*` manifest
builder, a `collect_*` function, and a `.sbatch`.

### How tools are discovered (and how override wins)

`sapia` scans the built-in tools dir first, then every dir in
`$PROSAPIA_TOOLS_DIR` (os.pathsep-separated, default `./tools`). Tools are keyed
by the `name` in their `spec.py`, and **later dirs win** — so a tool whose
`name` matches a built-in **shadows** it, while a new `name` registers a **new**
tool alongside the built-ins.

```bash
export PROSAPIA_TOOLS_DIR=./tools   # already the default
```

## Writing a `.sbatch`

Every tool's `.sbatch` receives two positional args and should source the shared
prelude, which the driver locates for it via `$SAPIA_PRELUDE`:

```bash
#!/bin/bash
#SBATCH ...

# Sets MANIFEST ($1), OUT_DIR ($2), and SAPIA_LINE (this array task's manifest line).
source "${SAPIA_PRELUDE:?}"

# Use $SAPIA_LINE and $OUT_DIR directly:
name=$(echo "$SAPIA_LINE" | cut -f1)
src=$(echo "$SAPIA_LINE"  | cut -f2)
...
```

The prelude is the one place the per-task boilerplate lives; tools cut their own
fields out of `$SAPIA_LINE` and write results under `$OUT_DIR`.
