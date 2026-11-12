# Cleaning a run

`sapia clean` retires the designs a campaign no longer needs and frees their files. You name a table and a filter. The rows the filter selects are **kept**, the same meaning as on `sapia run`. Every other row is cleaned:

- its files go;
- its `*_status` columns become `cleaned`;
- the cells that named a removed file are emptied.

The row itself stays, with its lineage and its metrics, so the table remains a record of every design the campaign produced and of which ones were cleaned.

Use it when a campaign is done and you want only the designs worth keeping on disk, or after a run whose filter was too wide. Cleaning is final:

- **Nothing selects a cleaned row again.** No run, resubmit, `--force` or collect picks it up, and neither does any tool downstream (see [Cleaned rows are final](#cleaned-rows-are-final)).
- **The files are gone.** Undoing a clean would mean rerunning every leaf it touched.

If you may still rerun those designs, don't clean them.

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
| `--leaf` | Free only this leaf's files and set only its `<leaf>_status`. The row is retired all the same: one `cleaned` status is enough. |
| `--descendants` | Also clean the live rows of other tables whose lineage runs through a cleaned row. Without it, clean refuses rather than leave live rows below retired ones. |
| `--ancestors` | Also clean every parent row left with no live child, then theirs, up the lineage. |
| `--dry-run` | Print what would be cleaned and exit. |

The filter sees the table with its ancestors' columns joined in, exactly as on `sapia run` (see [Writing a filter function](writing-a-filter-function.md#ancestor-columns)). Sequences can therefore be cleaned by their backbone's metrics.

A parent is never filtered by its children's metrics, since it has many children and their values don't reduce to one. Filter the children instead, and let `--ancestors` take the parents that have no live child left.

Rows already cleaned are skipped, so running the same clean twice does nothing the second time.

## An example

Five diffusions (`table0`), five ProteinMPNN sequences each (`table1`, 25 rows), AlphaFold3 run on `table1`. Two sequences pass, and you want everything else gone:

```bash
sapia clean "$RUN" -t table1 -w af3_pass=True --ancestors --dry-run
```

```
would keep 2 of 25 row(s) of table1
would mark 23 row(s) of table1 cleaned (proteinmpnn_status, af3_status)
would mark 3 row(s) of table0 cleaned, left without children (rfdiffusion_status)
would empty 41 cell(s) naming a removed file
would remove 64 file(s)/dir(s)
```

- The 23 failing sequences lose their AlphaFold3 outputs.
- The diffusions with no passing sequence lose their PDB, `.trb` and trajectories.
- The diffusions with a passing sequence stay live.

All 28 cleaned rows stay in their tables with status `cleaned`. Rerun without `--dry-run` to apply.

`--ancestors` checks every table. A diffusion that still has live sequences in another branch (say `table1_b`) stays live. A parent that never had children, for instance one you filtered out before ProteinMPNN, is never touched.

## What goes

- **Without `--leaf`:** every `*_status` of the row becomes `cleaned`, and its files go from every leaf of the table: the leaf that created it and every update leaf on it.
- **With `--leaf`:** only that leaf's files go and only its status changes. This is useful to free a large output, AlphaFold3's for example, while keeping the small upstream files to look at. A table with no status column yet gets its creating tool's `<tool>_status`.

A file or dir under a leaf's submission dirs belongs to:

- the design whose name it carries: exactly, or followed by `.`, `_` or `-` (`S0_1.json`, `S0_1_model.cif`, `traj/P_1_pX0_traj.pdb`). The longest matching name wins, so `P_1` never takes `P_10.pdb`;
- all of a parent's children, when it carries the parent's name (RFdiffusion's `P/`, ProteinMPNN's `seqs/P.fa`);
- the rows whose cells name it, and through its base name the files beside it (RFdiffusion3's `.json` beside the `.cif.gz`).

It goes once everything it belongs to is cleaned, now or by an earlier clean.

- **Dirs:** a dir that belongs only to cleaned designs goes whole, logs inside included.
- **What stays:** a file a live row still uses stays, and so do files that belong to no design: logs, shard and group files, `.meta.json`.
- **Converted PDBs:** one under `run_dir/.cif_to_pdb/` goes with its `.src` record and the source structure it records.
- **Symlinks:** they are removed, never followed.
- **Cells:** the cells of cleaned rows that named a removed file are emptied, while metrics and every other cell stay.

### Several children per parent

Children are cleaned one by one: the filter's selection is honoured exactly.

- **RFdiffusion** (`P` → `P_0` … `P_9`): cleaning `P_3` removes `P_3.pdb`, `P_3.trb` and its trajectories. `P/`, its renumbered input and `command.txt` belong to `P`, and `P/` goes whole with the last child.
- **ProteinMPNN** (`S` → `S_f1` … `S_f8`): nothing on disk belongs to one sequence, so cleaning `S_f3` retires its row and frees its outputs downstream. `seqs/S.fa` and the `inputs/S.pdb` link go with the last `S_f*`, and until then the cleaned rows still name the fasta.

## Cleaned rows are final

`cleaned` is a status the framework honours everywhere, through the shared ready check:

- **Run.** A row with any `cleaned` status is never ready: not on a resubmit, not with `--force`, and not for any tool downstream of the table, whatever its input column. A `create` tool counts a cleaned child as done, so a parent whose children were all cleaned isn't re-run.
- **Collect.** No collect writes over a cleaned row. An update leaf never marks it `missing`, and a create leaf doesn't bring back a cleaned child from a file its live siblings share (ProteinMPNN's fasta).
