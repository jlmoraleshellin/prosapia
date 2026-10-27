# Deleting a tool run

`sapia delete` removes a tool run as a unit: the leaf dir on disk and what that run wrote to the table. [`sapia collect`](collecting-a-tool.md) only reads: it marks a design `missing` when its output is gone but never removes anything. Delete is the repair step, and the way to rerun a tool from scratch or recreate a child table cleanly instead of `--force`-ing a `create` tool.

## The shape

```bash
sapia delete <run_dir> -t <table> --leaf <leaf> [--recursive] [--dry-run]
```

| Flag | Meaning |
| --- | --- |
| `run_dir` (positional) | The workflow directory. |
| `-t`, `--table` | **Required.** The table the leaf sits under: the table an `update` tool annotated, or the table a `create` tool made. |
| `--leaf` | **Required.** The leaf as written on disk and in column names: `<tool>` or `<tool>_<dir_label>`, e.g. `proteinmpnn_seed2`. |
| `--recursive` | When the leaf created its table, also delete every descendant table. |
| `--dry-run` | Print what would be removed and exit. |

No tool code is loaded: delete reads the leaf's `.meta.json` and the registry, so it also works for `merge` leaves and for tools that are no longer installed.

## What goes

A leaf lives under the table the tool **wrote to** (`run_dir/<table>/<leaf>/`), so there are two cases:

- **An `update` leaf.** The dir `run_dir/<table>/<leaf>/` goes (submissions, logs, sidecar), and so do the `<leaf>_*` columns of `<table>.tsv`. Every other column stays, including those of a same-tool variant with a longer label (deleting `proteinmpnn` keeps `proteinmpnn_seed2_*`). The table stays registered; a rerun on the same leaf starts again at `.submissions/00`.
- **A `create` or `merge` leaf.** Every column of that table came from this run, so the table goes: `<table>.tsv`, its registry row, and `run_dir/<table>/` with every update leaf inside. If the registry lists descendant tables, delete refuses and names them; `--recursive` deletes the whole subtree. The parent table is untouched.

Delete prints one line per thing it removes:

```
remove table1/af3/
drop 3 column(s) from table1: af3_status, af3_path, af3_plddt
```

## What stays

- **Manifests** under `run_dir/.manifests/` are kept as a record.
- **Downstream consumers.** A tool that read a deleted `<leaf>_path` as its input keeps what it collected; the table is a record, not a dependency graph.
- **Merged tables** that pooled a deleted table keep their rows; `merge_source` still names it.
- **Pending jobs** are not checked. Cancel a leaf's running array before deleting it, or its tasks will write into a dir that no longer exists.
