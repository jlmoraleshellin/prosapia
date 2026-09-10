# Architecture

## The idea: a powerful bench

`prosapia` is a **workbench, not a pipeline.** The goal is to make the *workspace* **flexible** while keeping each *tool* as simple as possible to **implement**. 

In `prosapia`:

1. **Tables are the data interface.** Tools never talk to each other; they read and write one shared, tabular data format. That decoupling is what lets you compose arbitrary tools dynamically, forking and back-tracking as the science demands, with no pipeline declared up front. → [The database](#the-database) and [the workspace](#the-workspace).

2. **Tools run in two phases.** On `run`, parallel tasks only write their own files on disk, then a single `collect` step folds them into the table. This keeps every table write safe under heavy parallelism and repeatable on reruns. → [The two-phase execution model](#the-two-phase-execution-model).

3. **The driver owns the orchestration.** Filtering, resume-on-rerun, SLURM submission, lineage stamping and table writes is all shared machinery. A tool contributes only metadata, two hooks, and a batch script; everything hard and tedious is already done. → [The drivers](#the-drivers).

## The database

Every protein-design tool speaks its own language on disk: RFdiffusion emits backbones as PDBs, ProteinMPNN emits FASTA sequences in a single file, AlphaFold3 emits structures plus confidence metrics... Stitching them together by hand means tailored glue for every pair of tools.

`prosapia` solves this by creating a shared data interface for tools that follows one rule: **a design is a row, a generation of designs is a table.** Each row is keyed by a design `name`; each tool contributes columns (a path to a structure, a sequence, a pLDDT, an RMSD, etc.). A tool never has to know which tool ran before it. It only reads the columns it needs and writes the columns it produces. The **collection of tables**, created through the design generations, is the **database**.

Tables are stored as `.tsv` and the [`DataManager`](#the-drivers) is the engine that handles them uniformly as `pandas.DataFrames` inside `prosapia`. Supported with the `_registry.tsv` (which is handled just like any other table), the `DataManager` does the relational work over them: lineage walks, cross-table joins, and inherited lookups.

## The workspace

Design workflows live inside a unique `run_dir`. Every tool needs one; `sapia new_run` mints a fresh one.

```
run_dir/
├── _registry.tsv         # catalog of every table + its lineage (parent, gen)
├── table0.tsv            # a table: one row per design, keyed by `name`
├── table1.tsv            # a child table (another generation)
├── .manifests/           # transient per-run manifests
└── table0/               # per-table, per-tool outputs on disk
    └── rfdiffusion/
        ├── <design>.pdb
        └── ...
```

The `*.tsv` tables are the shared data format; the nested directories are where tools drop their raw artifacts and where `collect_fn` reads them from.

## The two-phase execution model

Tools run in **two phases** against a `run_dir`: one to send the SLURM job and one to collect the outputs into a table.

![architecture](images/architecture.png)

The flow is the following:

1. User calls `sapia run <tool>` on an (*optional*) input table (`table0.tsv`) inside a `run_dir`. The driver takes care of the rest:
    1. It accesses the `run_dir` to: open the input table, reserve the output one (*see below*) check the rows that are **ready**, filter them (*if set*) and hand them to the tool's `build_manifest_fn`, which writes a tab-separated **manifest** textfile containing one line per array task.
    2. The driver then submits `tool.sbatch` (a SLURM array job) which consumes the manifest. Each task cuts its own fields out of its manifest line and writes results under `run_dir/<output_table>/<tool>/`  — keyed by the destination table reserved in step 1. The SLURM job parameters (concurrency, partitions, GPUs) can be specified through `sapia run` flags; documented in [Running a tool](running-a-tool.md).

2. User calls `sapia collec <tool>` on the output table (`table1.tsv`) inside the `run_dir`. The driver invokes the tool's `collect_fn`, which reads those on-disk outputs and writes rows into the destination table, creating it if needed.


> [!IMPORTANT]
> **The output table is derived, not chosen**
>
> You never name a tool's output table directly; the driver derives it in **phase 1** from the input table specified in `sapia run <tool>`. This behaviour depends on the tool's `action`:
> -  a **`create`** tool reserves that table's next generation: a fresh child named from its parent's generation and an optional `--table-label` passed to `sapia run <tool>`. (`table<gen+1>_<label>`). The driver registers it at submit time, before any task runs. (With no input table, a create tool starts a fresh root, table0.)
> - an **`update`** tool, on the other hand, does not reserve any table as it writes back into the one it read.
>
> This is why, by the time tasks finsish running, their outputs already land under `run_dir/<output_table>/<tool>/`.This way `sapia collect` is able to inmediately find the outputs location and fill the table that `run` reserved.


## The drivers

The `prosapia.core` package provides the two drivers, the tool-definition types, and the data layer.

| Module | Responsibility |
| --- | --- |
| `tool.py` | `Tool` (metadata + the two hooks) and `ToolMetadata` (`name`, `description`, `action`). |
| `base_sbatch.py` | `run_from_args(...)` — the submit-phase driver, shared by all tools. Resolves the destination table, calls `build_manifest_fn`, submits the SLURM array. |
| `base_collect.py` | `collect_from_args(...)` — the collect-phase driver. Invokes `collect_fn`, writes rows, updates the registry. |
| `data_manager.py` | `DataManager` — owns the run's tables and registry as DataFrames, resolves cross-table lineage, and exposes a read-only `lookup`. |
| `cli.py` | The `sapia` entrypoint. |

A **tool** is a composition of declarative metadata, two behavioral hooks, and scripts. It carries no orchestration logic of its own — the drivers supply that. See [Writing a tool](writing-a-tool.md).



Next: how tables relate to each other in [Lineage & tables](lineage-and-tables.md).
