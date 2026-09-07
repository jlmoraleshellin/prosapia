# Writing a collect function

A tool runs in two phases against a `run_dir`: the **run** fans designs out over
a SLURM array, and the **collect** reads what landed on disk back into the tool's
database. This guide is only about collect.

You write **one small function**. The framework does the rest: it iterates the
designs that are ready to collect, calls your function once per design, and writes
the results into the database — including the `<leaf>_status` and `<leaf>_path`
bookkeeping columns. **You never touch those column names.**

## The shape

A tool's `collect_fn` is a *factory*: it runs once per collect (do any one-time
directory scan here), and returns a per-design function that yields the rows one
design produced.

```python
from typing import Iterable
from prosapia.core import Collected, CollectCtx, CollectEach, DesignCtx


def collect_mytool(ctx: CollectCtx) -> CollectEach:      # runs once
    # ... one-time setup: scan ctx.out_dir, build an index, capture ctx.args ...

    def one(d: DesignCtx) -> Iterable[Collected]:        # runs per ready design
        # ... locate + parse this design's output, yield a Collected per row ...
        yield Collected(data={...}, path=..., status=...)

    return one
```

Wire it in `spec.py` like any hook — `collect_fn=collect_mytool`. That's the whole
contract; there is nothing else to register.

Why two functions? The outer one is where a one-time scan of the output directory
lives (so you don't re-scan per design); the inner one is pure per-design work. If
your tool needs no setup, the outer is just a thin wrapper that returns `one`.

## `DesignCtx` — what you get per design

The inner function receives one design at a time:

| Field | Meaning |
| --- | --- |
| `d.name` | the design's row name (an existing row for an `update` tool; the *parent* row for a `create` tool). |
| `d.out_dir` | this run's output directory (same as `ctx.out_dir`). |
| `d.leaf` | the tool's column prefix — use it to name your own columns, e.g. `f"{d.leaf}_ptm"`. |
| `d.lookup` | read a value from this design or any ancestor: `d.lookup(d.name, "n_subunits")`. |

Anything constant across designs — `ctx.args`, an index you built — you capture in
the outer function's closure.

## `Collected` — what you return

Yield one `Collected` per output row. Everything except `data` is optional:

| Field | Goes to | Default |
| --- | --- | --- |
| `data` | your tool-specific columns, written as-is | `{}` |
| `path` | the `<leaf>_path` column | not written |
| `status` | the `<leaf>_status` column | `"OK"` |
| `name` | overrides the row key (for `create` tools minting child rows) | the design's name |
| `parent` | the `parent_name` column (for `create` tools) | not written |

- **Yield one** `Collected` for an `update` tool — it annotates `d.name`.
- **Yield several** for a `create` tool — each with its own `name` and `parent`.
- **Yield nothing** when a design has no output on disk: an `update` tool marks the
  existing row `missing`; a `create` tool simply skips it.

To report a failure, yield a `Collected` with a non-`"OK"` status (`"missing"`,
`"empty"`, `"error: ..."` — any string that isn't `"OK"` counts as *not done*, so
the design is picked up again on the next collect). The framework treats `"OK"`
specially; everything else is retriable.

## Example — an `update` tool (AlphaFold3)

An `update` tool annotates rows that already exist (here, adds confidence metrics
and the model path to each predicted design). It yields exactly one `Collected`
per design.

```python
def collect_af3(ctx: CollectCtx) -> CollectEach:
    # Setup once: index every predicted design directory.
    design_dirs: dict[str, Path] = {}
    for shard_dir in sorted(ctx.out_dir.glob("results_shard_*")):
        for design_dir in shard_dir.iterdir():
            if design_dir.is_dir():
                design_dirs[design_dir.name] = design_dir

    na_metrics = {k: pd.NA for k in _get_af3_metrics(ctx.out_dir.name)}

    def one(d: DesignCtx) -> Iterable[Collected]:
        design_dir = design_dirs.get(d.name)
        if design_dir is None:
            yield Collected(status=f"missing: no output dir for {d.name}", data=na_metrics)
            return

        summary, cif = find_prediction_files(design_dir)
        if summary is None or cif is None:
            yield Collected(status=f"missing: no models in {design_dir}", data=na_metrics)
            return

        metrics = load_metrics(d.leaf, summary)      # {f"{d.leaf}_ptm": ..., ...}
        yield Collected(data=metrics, path=cif)      # status defaults to "OK"

    return one
```

Note what is *not* here: no `<leaf>_status` / `<leaf>_path` strings, no results
dict, no iteration over the database. You return values; the driver stamps
`alphafold3_status` / `alphafold3_path` and writes the row. (Yielding NA metrics on
a failure keeps those columns present even when every design fails — optional, but
tidy.)

## Example — a `create` tool (ProteinMPNN)

A `create` tool discovers **new** rows on disk. ProteinMPNN turns one input
structure into several designed sequences, so for each ready parent it yields one
child row per sequence, naming the child and its parent for lineage.

```python
def collect_mpnn(ctx: CollectCtx) -> CollectEach:
    # Setup once: map each parent row name -> its FASTA of sampled sequences.
    fasta_by_parent = build_fasta_index(ctx.out_dir)

    def one(d: DesignCtx) -> Iterable[Collected]:
        fasta = fasta_by_parent.get(d.name)          # d.name is the parent row
        if fasta is None:
            return                                    # no output -> create skips

        for i, (header, sequence) in enumerate(parse_fasta(fasta)):
            if i == 0:
                continue                              # skip the echoed input seq
            yield Collected(
                name=f"{d.name}_f{i}",                # the new child row's name
                parent=d.name,                        # -> parent_name (lineage)
                path=fasta,
                data={"iteration": i, "sequence": sequence, **parse_header(header)},
            )

    return one
```

The framework validates that each child's `parent` exists in the parent database
and stamps `parent_db` / `gen` for you — you only supply `parent`.

## The rare case — columns that aren't leaf-keyed

Almost every tool's status/path columns are keyed by the tool leaf, and the
defaults above handle that. If instead a single output directory hosts several
*named* results (e.g. one alignment tool that writes `boltz_vs_openfold3_TM1`,
`boltz_vs_af3_TM1`, …), put **every** column in `data` and set `status=None` to
suppress the leaf `<leaf>_status` stamp:

```python
yield Collected(status=None, data={f"{prefix}_status": "OK", f"{prefix}_TM1": tm})
```

## Rules the framework enforces

- **`create`**: each yielded row's `parent` must be a row in the parent database
  (for a child db). Don't set `parent_db` / `gen` — the framework does. Don't copy
  ancestor values into the child; read them later with `lookup`.
- **`update`**: yield rows for designs already in the database. A brand-new `name`
  triggers a warning — it usually means the tool should be `create`.
- **Resume is automatic.** Designs already collected `"OK"` are skipped on a re-run
  unless `--force`; you don't implement that.

## Checklist

1. Write `collect_<name>(ctx) -> CollectEach`: scan once in the outer function,
   return `one(d)`.
2. In `one`, locate this design's output and `yield Collected(...)` per row — or
   yield nothing if there's none.
3. Name your own columns with `d.leaf`; never write `<leaf>_status` / `<leaf>_path`
   yourself.
4. `create`: set `name` + `parent`. `update`: yield one row for `d.name`.
5. Wire `collect_fn=collect_<name>` in `spec.py`.
