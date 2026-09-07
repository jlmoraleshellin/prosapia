# Architecture

## The idea: a flexible bench, simple tools

`prosapia` is a **workbench, not a pipeline.** The goal is to make the *workspace* powerful and flexible while keeping each *tool* as simple as possible to implement. Two design choices carry that, and the rest of this page is how they work:

1. **The database is the interface.** Tools never talk to each other — they read and write one shared, tabular data format. That decoupling is what lets you compose arbitrary tools dynamically, forking and back-tracking as the science demands, with no pipeline declared up front. → [The shared   database](#the-shared-database) and [The workspace](#the-workspace).
2. **The driver owns the orchestration.** Filtering, resume-on-rerun, SLURM submission, lineage stamping, database writes — all shared machinery. A tool    contributes only metadata, two hooks, and a batch script; everything hard is    already done. → [The two-phase execution model](#the-two-phase-execution-model) and [The drivers](#the-drivers).

## The shared database

That first principle rests on collapsing a mess into one rule. Every
protein-design tool speaks its own language on disk: RFdiffusion emits backbones as PDBs, ProteinMPNN emits FASTA sequences, AlphaFold3 emits structures plus confidence metrics. Stitching them together by hand means bespoke glue for every pair of tools.

`prosapia` collapses that to one rule: **a design is a row, a generation of designs is a table.** Each row is keyed by a design `name`; each tool contributes columns (a path to a structure, a sequence, a pLDDT, an RMSD). A tool never has to know which tool ran before it — it only reads the columns it needs and writes the columns it produces. That uniformity is what lets arbitrary tools compose without a hard-coded pipeline.

Databases are stored as `.tsv` by default, but the [`DataManager`](#the-drivers) handles them uniformly as pandas DataFrames through a pluggable I/O backend, so the on-disk format is not load-bearing.

## The workspace

Design workflows live inside a unique `run_dir`. Every tool needs one; `sapia new_run` mints a fresh one.

```
run_dir/
├── _registry.tsv          # catalog of every database + its lineage (parent, gen)
├── db0.tsv                # a database: one row per design, keyed by `name`
├── db1_seqs.tsv           # a child database (another generation)
├── .manifests/            # transient per-run manifests
└── db0/                   # per-database, per-tool outputs on disk
    └── rfdiffusion/
        ├── <design>.pdb
        └── ...
```

The `*.tsv` databases are the shared data format; the nested directories are where tools drop their raw artifacts and where `collect_fn` reads them from.

## The two-phase execution model

Tool exectution requires **two** CLI commands; it runs in **two phases** against a `run_dir`. The shared driver owns the flow; the tool only knows about the variable part: which rows to submit, and how to read the results back.

![architecture](images/architecture.png)

The flow is the following:
1. User calls `sapia run <tool>` against an input db (`db0.tsv`) inside a `run_dir`. The driver opens the input database, reserves the destination database (see below), keeps the rows that are *ready* and hands them to the tool's `build_manifest_fn`, which writes a tab-separated **manifest** — one line per array task. 
2. The driver then submits a SLURM array job whose `tool.sbatch` consumes that manifest. Each task cuts its own fields out of its manifest line and writes results under `run_dir/<output_db>/<tool>/` — keyed by the destination database reserved in step 1. The `sapia run` flags that shape this array (concurrency, partitions, GPUs, filtering) are documented in [Running a tool](running-a-tool.md).
3. User calls `sapia collect` against the output db (`db1.tsv`) inside the `run_dir`. The driver invokes the tool's `collect_fn`, which reads those on-disk outputs, writes rows into the destination database and updates the registry. The manifest is transient scaffolding; the **database is the durable record.**

This is the second principle in action: the tool contributes only `build_manifest_fn` for `sapia run` and `collect_fn` for `sapia collect` (plus its `.sbatch`). Everything else — filtering, resume-on-rerun, SLURM submission, lineage stamping, database writes — is the shared driver. 

### The output database is derived, not chosen

You never name a tool's output database — the driver derives it in **phase 1**, the moment you call `sapia run`, from the input database plus the tool's `action`:

- an **`update`** tool writes back into the same database it read;
- a **`create`** tool reserves that database's **next generation** — a fresh child `db<gen+1>` linked to its parent — and registers it in the `_registry` immediately. (With no input database, a `create` tool starts a fresh root, `db0`.)

This is why, by the time tasks run in **phase 2**, their outputs already land under `run_dir/<output_db>/<tool>/`: the destination's identity precedes its rows. `sapia collect` in **phase 3** then fills the very database that `run` reserved.


## The drivers

The `prosapia.core` package provides the two drivers, the tool-definition types, and the data layer.

| Module | Responsibility |
| --- | --- |
| `tool.py` | `Tool` (metadata + the two hooks) and `ToolMetadata` (`name`, `description`, `action`). |
| `base_sbatch.py` | `run_from_args(...)` — the submit-phase driver, shared by all tools. Resolves the destination db, calls `build_manifest_fn`, submits the SLURM array. |
| `base_collect.py` | `collect_from_args(...)` — the collect-phase driver. Invokes `collect_fn`, writes rows, updates the registry. |
| `data_manager.py` | `DataManager` — owns the run's databases and registry as DataFrames, resolves cross-db lineage, and exposes a read-only `lookup`. |
| `cli.py` | The `sapia` entrypoint. |

A **tool** is a composition of declarative metadata, two behavioral hooks, and scripts. It carries no orchestration logic of its own — the drivers supply that. See [Writing a tool](writing-a-tool.md).



Next: how databases relate to each other in [Lineage & databases](lineage-and-databases.md).
