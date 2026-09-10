# Collecting a tool

`sapia collect` is the second phase: it turns a tool's on-disk outputs into table rows and columns. Where [`sapia run`](running-a-tool.md) submits a SLURM array, collect runs **locally and immediately** — no scheduling, no array — so it is intentionally small: a couple of flags and no SLURM knobs at all. See [the two-phase execution model](architecture.md#the-two-phase-execution-model) for how the two phases fit together.

## The shape

```bash
sapia collect <tool> <run_dir> -t <table> [flags]
```

`-t/--table` names the table the run wrote to — the reserved child for a `create` tool (e.g. `table1`), or the same table for an `update` tool. Unlike `sapia run`, it is **always required**: by collect time the destination table already exists (the run reserved it), so there is nothing to infer.

## Flags

| Flag | Default | Meaning |
| --- | --- | --- |
| `run_dir` (positional) | — | The workflow directory. |
| `-t`, `--table` | — | **Required.** The table to fill (name, no extension) — the table the run wrote to. |
| `-l`, `--dir-label` | `""` | Must match the run's `--dir-label`, so collect reads the same output dir (`run_dir/<table>/<leaf>/`) the run wrote to. See [Using labels](using-labels.md). |
| `--force` | off | Re-collect rows that are already filled in (skips the resume filter). |

There is **no `--input-column`** here. Collect reuses the column the run recorded in its sidecar (`.meta.json`), so the two phases can never disagree about which designs to process.

A tool may add its own collect flags (via  `add_collect_args_fn`); `sapia collect <tool> --help` is the authoritative list.

## What collect does

For each ready design it reads the tool's output under `run_dir/<table>/<leaf>/` and writes the resulting columns into `<table>.tsv`. The tool's `action` decides the contract:

- **`create`** stamps lineage on every new row (`parent_table`, `gen`) and validates that each row points at a real parent row — a create-collect fails if a child is missing its parent link.
- **`update`** writes the tool's columns back onto existing rows. It only *warns* (doesn't fail) if it produces a row not already in the table — a sign the tool should probably be `action="create"`.

If a ready design has no output on disk, an `update` marks its row `missing`; a `create` has no row yet, so it is skipped. Rerunning collect skips rows already marked `OK` unless you pass `--force`. When it finishes it prints how many rows it wrote:

```
Collected 128 row(s) into table1_seqs.
```

## Authoring the collector

This page is the CLI side. How a tool *produces* those rows — the `collect_fn` contract and what a collector returns — is covered in [Writing a collect function](writing-a-collect-function.md).
