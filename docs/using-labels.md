# Using labels to fork the outputs

Two independent labels let you run the same tool more than once in a workflow without collisions. They solve different problems:

- **`-l/--dir-label`** keeps same-tool *variants* apart **within one table** — each variant gets its own output dir and its own columns. Used by both `sapia run` and `sapia collect`.
- **`--table-label`** names the *child table* a `create` tool produces, to keep parallel **forks of the lineage** apart. Set at `sapia run`; `create` tools only.

| | `-l` / `--dir-label` | `--table-label` |
| --- | --- | --- |
| **Scopes** | output dir + columns *within* a table | the child *table* name |
| **Phases** | run **and** collect (must match) | run only |
| **Tools** | any | `create` only |
| **Use for** | same-tool variants (seeds, params) on the same designs | parallel forks / branches of the lineage |

## `--dir-label`: same-tool variants in one table

A tool writes to `run_dir/<table>/<leaf>/` and to the `<leaf>_status` / `<leaf>_path` columns, where the leaf is `<tool>` — or `<tool>_<dir-label>` when you pass one. So a dir-label gives a run its **own output dir and its own columns** in the same table, letting you run one tool several ways over the same designs.

The rule: **`sapia collect` must use the same `-l` as the run**, or it won't find the outputs (it looks under the labelled leaf) — collect errors with a "Output dir not found" if the labels disagree.

Predict structures for `table1` under two different seeds, side by side:

```bash
# variant A
sapia run     alphafold3 "$RUN_DIR" -t table1 -l seed1 ...
sapia collect alphafold3 "$RUN_DIR" -t table1 -l seed1

# variant B
sapia run     alphafold3 "$RUN_DIR" -t table1 -l seed2 ...
sapia collect alphafold3 "$RUN_DIR" -t table1 -l seed2
```

This leaves two output dirs and two column sets in the **same** `table1`:

```
run_dir/table1/alphafold3_seed1/     → columns alphafold3_seed1_status / _path
run_dir/table1/alphafold3_seed2/     → columns alphafold3_seed2_status / _path
```

Without `-l`, both runs would write to `run_dir/table1/alphafold3/` and the same `alphafold3_*` columns — the second would collide with the first.

## `--table-label`: forking the lineage

A `create` tool reserves a **new child table** for its output. By default that child is named `table<gen>` (the parent's generation plus one); `--table-label <name>` appends a label, giving `table<gen>_<name>`. Run a `create` tool twice from the same parent with different labels and you get two distinct children — a branch point.

Try two ProteinMPNN settings on the same backbones in `table0`:

```bash
# fork A: low sampling temperature
sapia run     proteinmpnn "$RUN_DIR" -t table0 --table-label lowT ...
sapia collect proteinmpnn "$RUN_DIR" -t table1_lowT

# fork B: high sampling temperature
sapia run     proteinmpnn "$RUN_DIR" -t table0 --table-label highT ...
sapia collect proteinmpnn "$RUN_DIR" -t table1_highT
```

Both children record `table0` as their parent in the registry, so lineage stays intact. Two things to note:

- **Collect has no `--table-label`.** The label lives in the *table name*, so you pass that name to `collect -t`. The `sapia run` output prints the destination table path, so you can read the name there (or check `_registry.tsv`).
- **The label carries forward.** It accumulates down generations, so a `create` tool run on `table1_lowT` reserves `table2_lowT` (and `table2_lowT_<new>` if you add another `--table-label`). The table name always tells you which fork you're on.

## Merging sibling tables: `sapia merge`

A fork is useful for comparing settings, but once you have picked (or want to keep both) the downstream tools would have to be run once per table. `sapia merge` pools sibling tables into one new child table, so the rest of the workflow runs once over all the designs:

```bash
sapia merge "$RUN_DIR" -t table1_lowT table1_highT          # -> table1_merged
sapia run   alphafold3 "$RUN_DIR" -t table1_merged ...
```

The rules:

- **Sources must share the same parent table.** Roots merge with roots. The merged table is registered as an ordinary child of that parent (same gen as its sources), so lineage, `lookup` and every later `run`/`collect` on it work unchanged. To pool lineages that diverged at the root, merge the roots first and run the next tool once on the merged root.
- **Sources are copied, not moved.** Rows keep their `parent_name`/`parent_table`/`gen` and every column (status, path, metrics); columns missing from one source are left empty. The source tables stay as they were.
- **Row names get a suffix** so they stay unique: the part of the source's label that distinguishes it from its siblings (`S0_f0` from `table1_lowT` becomes `S0_f0_lowT`). An unlabelled source keeps bare names. The merge refuses if names still collide.
- **`--table-label` names the merged table** by the usual child rule; it defaults to `merged`. The merge refuses to overwrite an existing table.

The merged table name is printed as the only stdout line so it can be captured, and its sources are recorded in `run_dir/<merged>/merge/.meta.json`.

## Combining them

#TODO improve combination explanation and logic
