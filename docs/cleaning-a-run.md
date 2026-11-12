# Cleaning a run

`sapia clean` frees the rows a campaign no longer needs. You name a table and a filter. The rows the filter selects are **kept**, the same meaning as on `sapia run`, and every other row is cleaned: dropped from the table, with every file that belongs to it. Tables, leaves and columns stay.

Use it when a campaign is done and you want only the designs worth keeping on disk, or after a run whose filter was too wide. Cleaning is final: the files are gone, and nothing remembers what was cleaned except a log you can read. If you may still rerun those designs, don't clean them.

[`sapia delete`](deleting-a-tool.md) is the other verb that removes things. It removes a whole leaf or table and changes the shape of the run.

## The shape

```bash
sapia clean <run_dir> -t <table> (-f filter.py | -w COL=VALUE ...) [--leaf <leaf>] [--descendants] [--ancestors] [--dry-run]
```

| Flag | Meaning |
| --- | --- |
| `run_dir` (positional) | The workflow directory. |
| `-t`, `--table` | **Required.** The table to clean. |
| `-f`, `--filter` | A module exposing `apply_filter(df) -> df`, as for `sapia run`. The rows it returns are kept. |
| `-w`, `--where` | `COL=VALUE`: keep only rows whose column equals the value (string compare). Repeatable, applied after `--filter`. One of `-f` / `-w` is required. |
| `--leaf` | Clean only this update leaf's results. The rows stay, their `<leaf>_*` cells are blanked and the leaf's files for them go. |
| `--descendants` | Also clean the rows of other tables whose lineage runs through a cleaned row. Without it, clean refuses rather than leave them orphaned. |
| `--ancestors` | Also clean every parent row this clean took the last child of, then theirs, up the lineage. |
| `--dry-run` | Print what would be removed and exit. |

The filter sees the table with its ancestors' columns joined in, exactly as on `sapia run` (see [Writing a filter function](writing-a-filter-function.md#ancestor-columns)). Sequences can therefore be cleaned by their backbone's metrics. A parent is never filtered by its children's metrics, since it has many children and their values don't reduce to one. Filter the children instead, and let `--ancestors` take the parents that have none left.

## An example

Five diffusions (`table0`), five ProteinMPNN sequences each (`table1`, 25 rows), AlphaFold3 run on `table1`. Two sequences pass, and you want everything else gone:

```bash
sapia clean "$RUN" -t table1 -w af3_pass=True --ancestors --dry-run
```

```
would keep 2 of 25 row(s) of table1
would drop 23 row(s) from table1
would drop 3 row(s) from table0 (left without children)
would remove 92 file(s)/dir(s)
would log to .clean_log.jsonl
```

The 23 failing sequences go with their AlphaFold3 outputs. The diffusions with no passing sequence go with their PDB, `.trb` and trajectories. The diffusions with a passing sequence stay. Rerun without `--dry-run` to apply.

`--ancestors` checks every table: a diffusion that still has sequences in another branch (say `table1_b`) stays. A parent that never had children, for instance one you filtered out before ProteinMPNN, is never touched.

## What goes

- **Without `--leaf`:** the cleaned rows are dropped from the table, and their files go from every leaf of that table: the leaf that created it and every update leaf on it.
- **With `--leaf`:** the rows stay, the leaf's `<leaf>_*` cells are emptied, and only that leaf's files for them go. A later collect of that leaf marks them `missing`, the same state as if they had been filtered out before the run. `--leaf` can't name the leaf that created the table; to clean its rows, omit `--leaf`.

A file or dir under a leaf's submission dirs belongs to:

- the design whose name it carries: exactly, or followed by `.`, `_` or `-` (`S0_1.json`, `S0_1_model.cif`, `traj/P_1_pX0_traj.pdb`). The longest matching name wins, so `P_1` never takes `P_10.pdb`;
- all of a parent's children, when it carries the parent's name (RFdiffusion's `P/`, ProteinMPNN's `seqs/P.fa`);
- the rows whose cells name it, and through its base name the files beside it (RFdiffusion3's `.json` beside the `.cif.gz`).

It goes once everything it belongs to is cleaned. A dir that belongs only to cleaned designs goes whole, logs inside included. A file a remaining row still uses stays, and so do files that belong to no design: logs, shard and group files, `.meta.json`. A converted PDB under `run_dir/.cif_to_pdb/` goes with its `.src` record and the source structure it records. Symlinks are removed, never followed.

### Several children per parent

Children are cleaned one by one: the filter's selection is honoured exactly.

- **RFdiffusion** (`P` → `P_0` … `P_9`): cleaning `P_3` removes `P_3.pdb`, `P_3.trb` and its trajectories. `P/`, its renumbered input and `command.txt` belong to `P`, and `P/` goes whole with the last child.
- **ProteinMPNN** (`S` → `S_f1` … `S_f8`): nothing on disk belongs to one sequence, so cleaning `S_f3` drops its row and its outputs downstream. `seqs/S.fa` and the `inputs/S.pdb` link go with the last `S_f*`. Until then the fasta still holds the cleaned sequences, and clean doesn't edit a tool's output. A later collect of that ProteinMPNN leaf would read them back as rows, so don't collect a leaf you cleaned.

## The log

Every clean that removes something appends one line to `run_dir/.clean_log.jsonl`:

```json
{"timestamp": "2026-11-12T10:03:41+00:00", "table": "table1", "leaf": null, "filter": null, "where": ["af3_pass=True"], "kept": 2, "removed": {"table1": ["S0_f1", "..."], "table0": ["S2", "..."]}, "files": 92}
```

It is for you to audit. Nothing in prosapia reads it.
