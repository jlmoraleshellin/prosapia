# Using labels to fork the outputs

Two independent labels let you run the same tool more than once in a workflow without collisions. They solve different problems:

- **`-l/--dir-label`** keeps same-tool *variants* apart **within one database** — each variant gets its own output dir and its own columns. Used by both `sapia run` and `sapia collect`.
- **`--db-label`** names the *child database* a `create` tool produces, to keep parallel **forks of the lineage** apart. Set at `sapia run`; `create` tools only.

| | `-l` / `--dir-label` | `--db-label` |
| --- | --- | --- |
| **Scopes** | output dir + columns *within* a db | the child *database* name |
| **Phases** | run **and** collect (must match) | run only |
| **Tools** | any | `create` only |
| **Use for** | same-tool variants (seeds, params) on the same designs | parallel forks / branches of the lineage |

## `--dir-label`: same-tool variants in one db

A tool writes to `run_dir/<db>/<leaf>/` and to the `<leaf>_status` / `<leaf>_path` columns, where the leaf is `<tool>` — or `<tool>_<dir-label>` when you pass one. So a dir-label gives a run its **own output dir and its own columns** in the same database, letting you run one tool several ways over the same designs.

The rule: **`sapia collect` must use the same `-l` as the run**, or it won't find the outputs (it looks under the labelled leaf) — collect errors with a "Output dir not found" if the labels disagree.

Predict structures for `db1` under two different seeds, side by side:

```bash
# variant A
sapia run     alphafold3 "$RUN_DIR" -d db1 -l seed1 ...
sapia collect alphafold3 "$RUN_DIR" -d db1 -l seed1

# variant B
sapia run     alphafold3 "$RUN_DIR" -d db1 -l seed2 ...
sapia collect alphafold3 "$RUN_DIR" -d db1 -l seed2
```

This leaves two output dirs and two column sets in the **same** `db1`:

```
run_dir/db1/alphafold3_seed1/     → columns alphafold3_seed1_status / _path
run_dir/db1/alphafold3_seed2/     → columns alphafold3_seed2_status / _path
```

Without `-l`, both runs would write to `run_dir/db1/alphafold3/` and the same `alphafold3_*` columns — the second would collide with the first.

## `--db-label`: forking the lineage

A `create` tool reserves a **new child database** for its output. By default that child is named `db<gen>` (the parent's generation plus one); `--db-label <name>` appends a label, giving `db<gen>_<name>`. Run a `create` tool twice from the same parent with different labels and you get two distinct children — a branch point.

Try two ProteinMPNN settings on the same backbones in `db0`:

```bash
# fork A: low sampling temperature
sapia run     proteinmpnn "$RUN_DIR" -d db0 --db-label lowT ...
sapia collect proteinmpnn "$RUN_DIR" -d db1_lowT

# fork B: high sampling temperature
sapia run     proteinmpnn "$RUN_DIR" -d db0 --db-label highT ...
sapia collect proteinmpnn "$RUN_DIR" -d db1_highT
```

Both children record `db0` as their parent in the registry, so lineage stays intact. Two things to note:

- **Collect has no `--db-label`.** The label lives in the *db name*, so you pass that name to `collect -d`. The `sapia run` output prints the destination db path, so you can read the name there (or check `_registry.tsv`).
- **The label carries forward.** It accumulates down generations, so a `create` tool run on `db1_lowT` reserves `db2_lowT` (and `db2_lowT_<new>` if you add another `--db-label`). The db name always tells you which fork you're on.

## Combining them

The two are orthogonal — `--db-label` picks *which lineage*, `-l` separates *variants within it*:

```bash
sapia run     proteinmpnn "$RUN_DIR" -d db0 --db-label lowT -l test_set ...
sapia collect proteinmpnn "$RUN_DIR" -d db1_lowT -l retry
```

→ `run_dir/db1_lowT/proteinmpnn_retry/`, columns `proteinmpnn_retry_*` in `db1_lowT`.
