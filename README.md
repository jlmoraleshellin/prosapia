# prosapia

`prosapia` is **a shared workbench for protein-design tools on HPC**. It's built with a single concept in mind: maximize *flexibility* while keeping *implementation* as simple as possible.

Tools share one bench: a **databases** they read from and write back to, and a **two-phase driver** that runs them on the cluster via SLURM. Each tool sets its results on the bench and picks up what earlier tools left.

See **[docs](docs/index.md)** for the full documentation.

## How it works in one picture

This is **not a pipeline framework.** There is no fixed order of steps. Instead there is a *consensus data format* — the database — and tools that consume and produce it. You compose a workflow dynamically by pointing the next tool at a database, exploring, forking, and back-tracking as the science demands. The database is the interface; the tools are interchangeable.

Every tool is ran in two CLI phases against a `run_dir`. The database is the durable record; the manifest is transient scaffolding for the SLURM job:

![architecture](docs/images/architecture.png)

See **[docs/architecture.md](docs/architecture.md)** for the full flow.

## Tools

A **tool** is anything that **creates or updates a database**. RFdiffusion creating backbones, ProteinMPNN designing sequences, an AlphaFold3 prediction annotating rows in place: each is just a tool that writes to the bench.

`prosapia` implements many popular tools for you (RFdiffusion, ProteinMPNN, AlphaFold3, Boltz, etc.) as thin wrappers that plug into the driver. It does **not install the underlying software**. You install each binary or environment yourself and **bind** it to prosapia with a small activation script (see [Configuration](docs/configuration.md)).

Need a tool that isn't bundled? **[Write your own](docs/writing-a-tool.md).**

## Installation

`prosapia` is a `pip`-installable library. Install it into a dedicated environment and build your pipeline there.

```bash
python -m venv .venv
source .venv/bin/activate

pip install git+https://github.com/jlmoraleshellin/prosapia.git
```

> [!NOTE]
prosapia will be published to PyPI — `pip install prosapia` will work in the future.

Verify the CLI is available and enable shell tab-completion:

```bash
sapia --help
sapia init          # one-time: install shell completion
```

## Configuration

prosapia ships the tool *implementations* but not the software behind them: you install each binary or environment yourself (RFdiffusion, ProteinMPNN, Rosetta, …) and **bind** it to prosapia. Each tool needs a minimal **activation** shell snippet, sourced by its `.sbatch` to make the binary, environment, or input paths available to the SLURM job.

### Quick guide to bind a tool:

See **[docs/configuration.md](docs/configuration.md)** for the full activation-script model and complete guide.

1. **Scaffold the starter config.** `sapia init --config` writes a `.env` seed and an `activation/` dir of runnable per-tool templates into the current directory.

   ```bash
   sapia init --config
   ```

2. **Edit the tool's activation script** (`activation/<name>.sh`) to point at your install.

   ```bash
   # activation/rfdiffusion.sh
   source "$CONDA_PREFIX/etc/profile.d/conda.sh"
   conda activate SE3nv
   export RUN_INFERENCE="/path/to/RFdiffusion/scripts/run_inference.py"
   ```

3. **Point `SAPIA_ACTIVATE_<NAME>` at it from your `.env`**

   ```bash
   $EDITOR .env   # SAPIA_ACTIVATE_RFDIFFUSION → the script above
   ```

`.env` itself holds only global settings, those `SAPIA_ACTIVATE_<NAME>` pointers, and the few values prosapia reads at submit time.

### Sharing custom tools across environments

`sapia` discovers built-in tools first, then any directory in **`PROSAPIA_TOOLS_DIR`** (default `./tools`) — point it at a shared location to reuse custom tools across environments.

 See [Configuration](docs/configuration.md#tool-discovery-and-sharing) for how discovery and shadowing work.

## Quick start

```bash
sapia init                                 # one-time: shell tab-completion
RUN_DIR=$(sapia new_run --label demo)      # mint a run_dir (prints its path)

# de-novo backbones → a root database
sapia run     rfdiffusion "$RUN_DIR" ...
sapia collect rfdiffusion "$RUN_DIR" -d db0

# design sequences for those backbones → a child database
sapia run     proteinmpnn   "$RUN_DIR" -d db0 ...
sapia collect proteinmpnn   "$RUN_DIR" -d db1

# predict structures and score them *in place* on the sequence database
sapia run     alphafold3  "$RUN_DIR" -d db1 ...
sapia collect alphafold3  "$RUN_DIR" -d db1
```

`run_dir` is a positional argument to every tool; `-d/--database` names the
database to consume. Omit `-d` on a `create` tool to start a fresh root lineage.
Only `sapia new_run` mints a `run_dir`; tools always operate inside an existing
one.

Every tool shares base `sapia run` flags — concurrency, partitions, GPUs, filtering, resume — and how they map to SLURM. See **[docs/running-a-tool.md](docs/running-a-tool.md)** for the full reference.

## Two kinds of tools: `create` vs. `update`

A tool's `action` decides how its output relates to its input — and it encodes a biological rule:

**When a protein diverges in sequence or structure, it is no longer the same protein, so it needs a new database.**

- **`create`** mints a **new child database** (a new generation, `gen+1`) and links each new row to its parent. Use it when the tool *produces new entities*: RFdiffusion emits new backbones (and swaps side chains for glycines — a new  sequence); each diffusion is a distinct structure; ProteinMPNN turns one backbone into many new sequences. 
- **`update`** annotates the **same database in place**, adding columns to existing rows. Use it when the tool *measures a property* of designs that already exist: an AlphaFold3 / ColabFold / Boltz prediction is a property of *that* protein — not a new one — and a USalign score just annotates it.

Nothing about the resulting lineage tree is declared up front — each edge is just another `sapia run` / `sapia collect`. Read more, and see the tree diagram, in **[docs/lineage-and-databases.md](docs/lineage-and-databases.md)**.

## Customizing and writing tools

A tool carries **no orchestration logic** — the driver supplies that. It is just metadata plus two hooks and a batch script. You can override a single hook on a bundled tool, fork a whole tool, or write one from scratch. See:

- **[docs/writing-a-tool.md](docs/writing-a-tool.md)** — the four pieces, the
  three ways to customize, and the `.sbatch` prelude.
- **[docs/writing-a-collect-function.md](docs/writing-a-collect-function.md)** —
  the `collect_fn` contract with worked `create` and `update` examples.


## Documentation

More detailed docs live under [`docs/`](docs/index.md):

- [Architecture](docs/architecture.md) — the shared database and the two-phase driver.
- [Running a tool](docs/running-a-tool.md) — the `sapia run` flags and how they map to SLURM.
- [Collecting a tool](docs/collecting-a-tool.md) — the `sapia collect` phase and its flags.
- [Using labels](docs/using-labels.md) — `--dir-label` and `--db-label` for variants and forks.
- [Using RFdiffusion](docs/tools/rfdiffusion.md) and [using ProteinMPNN](docs/tools/proteinmpnn.md) — the two bundled tools with their own expression languages.
- [Lineage & databases](docs/lineage-and-databases.md) — `create` vs. `update`, roots, and `lookup`.
- [Configuration](docs/configuration.md) — the full environment-variable reference.
- [Writing a tool](docs/writing-a-tool.md), [writing a build-manifest function](docs/writing-a-build-manifest-function.md), [writing a collect function](docs/writing-a-collect-function.md), and [writing a filter function](docs/writing-a-filter-function.md).


## Contributing




## License

[MIT](LICENSE) © Jose
