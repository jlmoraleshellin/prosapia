# Writing a build-manifest function

A **build-manifest function** is the submit-phase hook of a tool: it reads the designs a run should process and returns one **manifest row** per array task. The driver writes those rows tab-separated to a manifest `.txt`, then submits a SLURM array whose per-task `.sbatch` consumes one line each. It is the tool's answer to a single question — *"what are the per-task inputs for this run?"* — and it carries no orchestration itself: filtering, resume, submission, and lineage are the [driver](architecture.md#the-drivers)'s job.

## The contract

The function takes a `ManifestCtx` and returns a sequence of rows, where each row is itself a sequence of string fields (`ManifestRow = Sequence[str]`) with one row per array task:

```python
from prosapia.core import ManifestCtx, ManifestRow

def build_mytool_manifest(ctx: ManifestCtx) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    for name in ctx.ready.index:                    # only the ready designs
        src = ctx.ready.at[name, ctx.args.input_column]
        rows.append((name, str(src)))               # fields your .sbatch will cut
    return rows
```

Every field is written as a string, so cast paths and numbers yourself. Return an empty list and the run prints `No designs to submit.` and exits.

## The context

`ctx` is a `ManifestCtx` that exposes everything the hook may read. The most important field is **`ctx.ready`**: the designs this run should submit — rows with a present `--input-column`, minus those the tool already finished (`<leaf>_status == "OK"`) unless `--force`. Iterate `ctx.ready` and you get resume-on-rerun and input filtering for free; you never filter or resume by hand (see [the ready set](running-a-tool.md#the-ready-set)). The rest: **`ctx.df`** is the full source frame (use it only when you deliberately select rows a different way than `--input-column`), **`ctx.args`** is the parsed CLI namespace (the base flags plus any your `add_run_args_fn` added), **`ctx.out_dir`** is the destination output dir for this run (write any staged inputs under it), and **`ctx.lookup`** walks the lineage to inherit an ancestor's value — `ctx.lookup(name, "n_subunits")` reads that column from the row or its nearest ancestor.

## Rows and the `.sbatch`

A row's fields become one tab-separated manifest line, and the tool's `.sbatch` cuts them back out in the order you emitted them — `name=$(echo "$SAPIA_LINE" | cut -f1)`, `src=$(… | cut -f2)`, and so on. So the **field order is the contract between the manifest builder and the `.sbatch`**: whatever you append here, the script must cut in the same positions (see [Writing a `.sbatch`](writing-a-tool.md#writing-a-sbatch)). Keep the fields to what a task needs to run — a name, one or two input paths, an output prefix — and derive the rest inside the script.

## Common patterns

The one-row-per-design loop above is the base case; bundled tools layer three variations on it. **Per-design staging** does deterministic, input-derived prep *here* at submit time and puts only the staged path in the row, so the `.sbatch` just launches the binary — RFdiffusion renumbers each input PDB into `ctx.out_dir`, ColabFold writes a FASTA per design, and the row carries the staged file's path. **Sub-manifests** let one array task cover several designs: pack N designs into a per-task file and emit that file's path as the row's single field (RFdiffusion's `--per-card` groups diffusions onto one GPU this way). **Custom selection** bypasses `ctx.ready` when a tool keys off its own columns rather than `--input-column` — USalign filters `ctx.df` by `--col-a` — but if you do this, replicate the resume skip yourself (drop rows whose `<prefix>_status == "OK"` unless `--force`), since you're no longer getting it from `ctx.ready`.

## Where it lives

The build-manifest function is one of a tool's two hooks, wired into its `spec.py` as `build_manifest_fn` (with any extra CLI flags supplied by `add_run_args_fn`). See [Writing a tool](writing-a-tool.md) for the full anatomy and [Writing a collect function](writing-a-collect-function.md) for its collect-phase counterpart.
