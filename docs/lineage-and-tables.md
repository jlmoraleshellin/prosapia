# Lineage & tables

## The prosapia principles

1. **A design is a row, a generation of designs is a table.**

2. **When a protein diverges in sequence or structure, it is no longer the same protein but a child of a parent — therefore it needs a new table.**

Everything about how tables relate to each other follows from this. A tool *updates* a table when it derives a property of its entities, a tool *creates* a table the moment it spawns genuinely new entities.

## `create` vs. `update`

A tool's `action` encodes which side of that rule it falls on:

### `create` — new entities, new table

`create` reserves a **new child table** (a new generation, `gen+1`) and links
each new row back to its parent row. Use it when the tool *produces new entities*:

- **RFdiffusion** emits new backbones — and swaps side chains for glycines, so even a single diffusion yields a new *sequence*. Multiple diffusions share that glycine sequence but are different *structures*. Either way: new entities.
- **ProteinMPNN** turns one backbone into many new sequences — one parent row fans out to N child rows.

### `update` — a property of an existing entity, same table

`update` annotates the **same table in place**, adding columns to existing rows. Use it when the tool *measures a property* of designs that already exist:

- **AlphaFold3 / ColabFold / OpenFold3 / Boltz** predict a structure for a  sequence. That structure is a **property of that protein** just like its prediction metrics. So it annotates the row in place rather than minting a generation.
- **USalign** derives metrics from structures (RMSD / TM-score) — again, a property written back onto the existing row.

> [!NOTE]
> While a `create` tool's `sapia run` and `sapia collect` point to separate tables, an `update` tool's point to the same one.

## Roots and the lineage tree

A `create` tool run with no `--table` starts a fresh lineage by creating a **root** table (`gen 0`). From there, each tool that acts on a table following [the second principle](#the-prosapia-principles) will spawn a new table generation.

Nothing about the top graph (*see below*) is declared up front. Each edge is just one more `sapia run` / `sapia collect` pointed at a table. Forking is also possible (e.g. trying two ProteinMPNN settings on the same backbone), learn [how to](using-labels.md).


![architecture](images/architecture.png)


To produce the workflow above, the CLI inputs would look like this:
```bash
# de-novo backbones → a root table
sapia run     rfdiffusion "$RUN_DIR" ...
sapia collect rfdiffusion "$RUN_DIR" -t table0

# design sequences for those backbones → a child table
sapia run     proteinmpnn   "$RUN_DIR" -t table0 ...
sapia collect proteinmpnn   "$RUN_DIR" -t table1

# predict structures and score them *in place* on the sequence table
sapia run     alphafold3  "$RUN_DIR" -t table1 ...
sapia collect alphafold3  "$RUN_DIR" -t table1
```

## Inheriting values across generations: `lookup`

Because every row records its `parent_table` / `parent_name` (and `gen`), a `lookup` function walks the lineage chain to inherit an ancestor's value. A downstream tool can read a property set generations earlier without copying it forward at every step — the lineage links are the single source of truth, and `DataManager` resolves them for you.
