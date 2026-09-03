# Lineage & databases

## The governing rule

**When a protein diverges in sequence or structure, it is no longer the same
protein — so it needs a new database.**

Everything about how databases relate to each other follows from this. A database
holds designs that are "the same entity" observed across tools; a *new* database
is born the moment a tool creates genuinely new entities.

## `create` vs. `update`

A tool's `action` encodes which side of that rule it falls on:

### `create` — new entities, new database

`create` reserves a **new child database** (a new generation, `gen+1`) and links
each new row back to its parent row. Use it when the tool *produces new entities*:

- **RFdiffusion** emits new backbones — and swaps side chains for glycines, so
  even a single diffusion yields a new *sequence*. Multiple diffusions share that
  glycine sequence but are different *structures*. Either way: new entities.
- **ProteinMPNN** turns one backbone into many new sequences — one parent row
  fans out to N child rows.

### `update` — a property of an existing entity, same database

`update` annotates the **same database in place**, adding columns to existing
rows. Use it when the tool *measures a property* of designs that already exist:

- **AlphaFold3 / ColabFold / OpenFold3 / Boltz** predict a structure for a
  sequence. That structure is a **property of that protein** just like its predicition metrics. So it annotates the row in
  place rather than minting a generation.
- **USalign** scores a structure (RMSD / TM-score) — again, a property written
  back onto the existing row.

## Roots and the lineage tree

A **root** database (`gen 0`) starts a fresh lineage: a `create` tool run with no
`--database`. From there, databases form a tree, catalogued in the run's
`_registry.tsv`.

> [!NOTE]
> **Root mode ≠ de-novo.** "Root mode" means *no `--database` input* — start a
> fresh lineage rather than iterate an existing db column. A root run may still
> take a single input structure directly on the CLI (e.g. RFdiffusion's
> `--input-pdb` for partial/motif diffusion of one structure not yet in any db).
> Root **with** an input structure lets you *start* a pipeline from a diffusion;
> root **without** one is pure de-novo.

```mermaid
flowchart TD
    S(["de-novo · no --database"])
    R[("db0 · root<br/>backbones")]
    A[("db1<br/>sequences")]

    S -->|"create: rfdiffusion"| R
    R -->|"create: mpnn_seqs<br/>1 backbone → N sequences"| A
    A -->|"update: alphafold3<br/>predict + score in place"| A
    A -->|"update: Alphafold3<br/>structure predicitions"| A

    classDef db fill:#e8f0fe,stroke:#4285f4,color:#111;
    class R,A db;
```

Nothing about this tree is declared up front. Each edge is just one more
`sapia run` / `sapia collect` pointed at a database — so branching (e.g. trying
two ProteinMPNN settings from the same backbones) is just running the tool twice
with different labels.

## Inheriting values across generations: `lookup`

Because every row records its `parent_db` / `parent_name` (and `gen`), a `lookup` function
walks the lineage chain to inherit an ancestor's value. A downstream tool can read
a property set generations earlier without copying it forward at every step — the
lineage links are the single source of truth, and `DataManager` resolves them for
you.
