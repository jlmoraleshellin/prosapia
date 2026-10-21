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

- **Sources must share the same gen.** Siblings (same parent) merge into an ordinary child of that parent, so lineage, `lookup` and every later `run`/`collect` on it work unchanged. Roots merge with roots. Cousins work too, see [Merging cousins](#merging-cousins) below.
- **Sources are copied, not moved.** Rows keep their `parent_name`/`parent_table`/`gen` and every column (status, path, metrics); columns missing from one source are left empty. The source tables stay as they were.
- **Row names get a suffix** so they stay unique: the part of the source's label that distinguishes it from its siblings (`S0_f0` from `table1_lowT` becomes `S0_f0_lowT`). An unlabelled source keeps bare names. The merge refuses if names still collide.
- **`--table-label` names the merged table** by the usual child rule; it defaults to `merged`. The merge refuses to overwrite an existing table.

The merged table name is printed as the only stdout line so it can be captured, and its sources are recorded in `run_dir/<merged>/merge/.meta.json`.

### Per-fork inputs after a merge

Merge the forks as soon as the `create` step that made them is collected, and keep working on one table. Every merged row carries a `merge_source` column with the table it came from, so a tool that needs fork-specific arguments is run once per fork on the merged table with `--where`, under the **same** leaf:

```bash
sapia run     boltz "$RUN_DIR" -t table1_merged -w merge_source=table1_lowT  --use-msa-server
sapia run     boltz "$RUN_DIR" -t table1_merged -w merge_source=table1_highT --msa-empty-chains
sapia collect boltz "$RUN_DIR" -t table1_merged      # one collect picks up both runs
```

Both runs write to `run_dir/table1_merged/boltz/` and the `boltz_*` columns, so downstream tools see one table and one column set. Each submission gets its own manifest, so a second run never disturbs tasks still pending from the first. The one limit: runs sharing a leaf must use the same `--input-column`, because collect reads the input column recorded by the last run.

This is the recommended way to analyse forks differently. Running each fork through its own child table instead leaves you with cousin tables, which are harder to pool.

### Merging cousins

If forks already went through a generation on their own, their children are cousins: same gen, different parents. `sapia merge` still pools them, by first merging their parents (recursively, up to the common ancestor or the roots) under the same label. Those intermediate tables are ordinary merged tables, so every table keeps one parent and every row's parent resolves:

```bash
sapia merge "$RUN_DIR" -t table2_x_a table2_x_b
# creates table1_x_merged (rows of table1_x_a/table1_x_b, suffixed a/b)
# then    table2_x_merged (rows re-pointed to their copies in table1_x_merged)
```

Keep in mind:

- The intermediate merges **copy** the ancestor rows. Columns added to the original parents after the merge are not reflected in the copies.
- If you merged the parents earlier under the same label, that table is reused as long as it lists the same sources; otherwise the merge refuses and asks for another label.
- Row suffixes accumulate along the path (`S0_f0_d0` from `table2_x_a` becomes `S0_f0_d0_a`), and labels do not: the levels are `table1_x_merged`, `table2_x_merged`.

#### Gen gaps: `--lift`

If one fork took an extra step (say a relax round) and the other did not, the tables you want to pool differ in gen. `sapia merge ... --lift` accepts that: the shallower table joins the merge at its own gen (as a ghost source) and is then carried up through pass-through copies, one per missing level, each copy pointing at its own copy one level down with `gen` restamped. Without `--lift` a gen gap is refused, because padding a lineage asserts that the shallower fork legitimately skipped a step, which the merge cannot check.

```bash
sapia merge "$RUN_DIR" -t table3_x_a table2_x_b --lift
# table2_x_merged <- table2_x_a + table2_x_b          (ghost, parent table1_x)
# table3_x_merged <- table3_x_a + lifted table2_x_b   (parent table2_x_merged)
```

Prefer merging siblings right after the fork and using `--where` for fork-specific runs; cousin merges are the escape hatch.

## Combining them

#TODO improve combination explanation and logic
