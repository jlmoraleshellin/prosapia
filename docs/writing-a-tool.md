# Writing a tool

## What is a tool?

A **tool** is anything that **creates or updates a database**. It carries **no orchestration logic**; the [drivers](architecture.md#the-drivers) supply that. A tool is just declarative metadata, two behavioral hooks, and a batch script.

prosapia bundles ready-made implementations for many popular tools (RFdiffusion, ProteinMPNN, AlphaFold3, and more), but it does **not install the underlying software** — you install and [bind](configuration.md) that yourself. When a tool you need isn't bundled, you write your own; when a bundled one nearly fits, you customize it. This guide covers both: the anatomy, the `.sbatch` contract, the [three ways to customize](#customizing-bundled-tools), and how tools are discovered.

## The four pieces

| Piece | What it is |
| --- | --- |
| **metadata** (`Tool` / `ToolMetadata`) | `name`, `description`, and `action` (`create` / `update`), plus `default_sbatch` and `default_input_column`. |
| **`build_manifest_fn`** | reads the ready rows, returns one manifest line (a `Sequence[str]`) per array task. |
| **`collect_fn`** | a collector factory: runs once per collect, returns a per-design function that yields the rows a design produced (see [Writing a collect function](writing-a-collect-function.md)). |
| **`tool.sbatch`** | the per-array-task script; receives the manifest and `out_dir` as positional args. |

An optional `tool_worker.py` can do extra Python work per task. If the per-design step is a simple shell command, put it directly in `tool.sbatch` instead.

## Tool directory layout

A tool is a folder discovered by `sapia`. A typical one:

```
mytool/
├── spec.py                     # exports TOOL = Tool(...)
├── run_mytool_sbatch.py        # build_manifest_fn (+ optional add_run_args_fn)
├── collect_mytool.py           # collect_fn (+ optional add_collect_args_fn)
├── mytool.sbatch               # per-array-task script
└── mytool_worker.py            # (optional) per-task Python
```

> [!NOTE]
> The only necessary files are `mytool.sbatch` and `spec.py`. The driver functions can be written in any python file inside the directory, even in `spec.py`.

### `spec.py`

`spec.py` binds everything together into a single `Tool` and exports it as `TOOL`:

```python
from pathlib import Path

from prosapia.core import Tool

from .collect_mytool import collect_mytool, _add_collect_args
from .run_mytool_sbatch import build_mytool_manifest, _add_run_args

TOOL = Tool(
    name="mytool",
    action="update",                        # or "create"
    description="What this tool does.",
    default_sbatch=str(Path(__file__).parent / "mytool.sbatch"),
    default_input_column="pdb_path",        # which db column feeds the tool
    build_manifest_fn=build_mytool_manifest,
    collect_fn=collect_mytool,
    add_run_args_fn=_add_run_args,          # optional: extra `sapia run` flags
    add_collect_args_fn=_add_collect_args,  # optional: extra `sapia collect` flags
)
```

Pick `action` with the [lineage rule](lineage-and-databases.md) in mind: `create` if the tool produces **new entities** (a new database generation), `update` if it measures a **property** of designs that already exist.

### `build_manifest_fn`

The submit-phase hook. It receives a `ManifestCtx` and returns one **manifest row** (a `Sequence[str]`, written tab-separated) per array task:

```python
from prosapia.core import ManifestCtx, ManifestRow

def build_mytool_manifest(ctx: ManifestCtx) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    for name, row in ctx.ready.iterrows():          # only the ready designs
        src = row[ctx.args.input_column]
        rows.append((name, str(src)))               # fields your .sbatch will cut
    return rows
```

`ctx` exposes the input frame (`ctx.df`), the parsed CLI args (`ctx.args`), the output directory (`ctx.out_dir`), a lineage `ctx.lookup`, and — most importantly — `ctx.ready`: the designs this run should submit (rows with a present input column, minus those the tool already finished, unless `--force`). You never filter or resume by hand. See the dedicated [Writing a build-manifest function](writing-a-build-manifest-function.md) guide for the full contract, the context fields, and the common staging / sub-manifest / custom-selection patterns.

### `collect_fn`

The collect-phase hook is a **factory**: `collect_mytool(ctx) -> CollectEach` runs once per collect (do any one-time output scan here) and returns a per-design function that `yield`s a `Collected` for each row a design produced. The driver iterates the ready designs and stamps the `<leaf>_status` / `<leaf>_path` / `parent_name` columns for you. See the dedicated [Writing a collect function](writing-a-collect-function.md) guide for the full contract with `create` and `update` examples.

## Writing a `.sbatch`

Every tool's `.sbatch` receives two positional args — the manifest (`$1`) and the `out_dir` (`$2`) — and sources two things in order: the shared **prelude** (located via `$SAPIA_PRELUDE`) and the user's **activation script** (via `$SAPIA_ACTIVATE_<NAME>`, [required](#environment-activation)):

```bash
#!/bin/bash
#SBATCH ...

# Sets MANIFEST ($1), OUT_DIR ($2), and SAPIA_LINE (this array task's manifest line).
source "${SAPIA_PRELUDE:?}"

# Site-specific activation (required) — see "Environment activation" below.
set +u
source "${SAPIA_ACTIVATE_MYTOOL:?set SAPIA_ACTIVATE_MYTOOL in your .env to a tool activation script}"
set -u

# Cut your own fields out of $SAPIA_LINE and write results under $OUT_DIR:
name=$(echo "$SAPIA_LINE" | cut -f1)
src=$(echo "$SAPIA_LINE"  | cut -f2)
# ... run the tool, writing into "$OUT_DIR" ...
```

The prelude is the one place per-task boilerplate lives: it resolves `MANIFEST`,
`OUT_DIR`, and this array task's line as `SAPIA_LINE`. Tools cut their own fields
out of `$SAPIA_LINE` and write results under `$OUT_DIR`.

### Environment activation

**Do not hard-code activation** (`conda activate`, `module load`, `source
<activate>`) in your `.sbatch` — that is site-specific and belongs to the user. Instead add the standard activation block right after you source the prelude (as in the skeleton above): source the user's `SAPIA_ACTIVATE_<NAME>` script (`<NAME>` = your tool's `name`, upper-cased; see [Configuration](configuration.md#how-binding-works)). Make it **required** — a batch job starts from a bare shell, so failing fast beats running against the wrong environment. You may still expose an **optional path override that defaults to `PATH`** for the binary the user's script puts there:

```bash
# defaults to PATH; user may set MYTOOL_BIN to a specific path
"${MYTOOL_BIN:-mytool}" "$input" --out "$OUT_DIR"
```

The `:?` makes the variable required and fails the job with a clear message when it is unset. The `set +u` guard matters — activation scripts often reference unset vars. Keep genuine *inputs* (script paths, container/weights/db paths) as their own named variables read in the `.sbatch`; the user exports them from the same activation script alongside activation, which is also where any per-tool runtime setup (framework caches, extra env vars) belongs (see [Configuration](configuration.md)). The exception is any input you read in Python at **submit time** (e.g. `os.getenv` in your build-manifest step) — that runs before the activation script, so it must come from `.env`.

## Customizing bundled tools

The bundled tools are intentionally general and may not fit every workflow. Three ways to adapt them, from lightest to heaviest:

### 1. Reuse a bundled tool, override just what you need

`Tool` is a frozen dataclass; `get_builtin` fetches a bundled one and `with_overrides` returns a copy with some fields swapped. In your own `spec.py`, reuse everything and replace only the hook that differs:

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

Add a folder with a `spec.py` exporting `TOOL = Tool(...)`, a `run_*` manifest builder, a `collect_*` function, and a `.sbatch` — as laid out above.

## How tools are discovered

`sapia` scans the built-in tools first, then every directory in
`$PROSAPIA_TOOLS_DIR` (default `./tools`), keying tools by the `name` in their
`spec.py`. Later directories win, so a custom tool can **shadow** a built-in of
the same `name` or register **alongside** it under a new one. See
[Configuration](configuration.md#tool-discovery-and-sharing) for the full rules
and how to share a tools directory across environments.
