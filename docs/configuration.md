# Configuration

`prosapia` does not bundle tools. You provide your own external binaries and environments (RFdiffusion, ProteinMPNN, Rosetta, etc.) and *bind* them to prosapia through **environment variables**, loaded from a `.env` file in your working directory. You only need to configure the tools you actually run.

## How binding works

Every tool needs **activation**: making its binary available to the job, by activating a conda env, loading a module, or sourcing an activate script. Most tools also need their own **input paths** — a script path like `RUN_INFERENCE`, a checkout root like `PROTEIN_MPNN`, the AF3 container/params/db. Both live together in a per-tool **activation script**.

Each tool's `.sbatch` sources that script before it runs the tool. It finds the script through the variable **`SAPIA_ACTIVATE_<NAME>`**. The `.sbatch` sources it unconditionally; if the variable is unset the job fails fast with a clear message. That is the whole contract, open any tool's `.sbatch` and you will see the exact lines:

```bash
set +u
source "${SAPIA_ACTIVATE_COLABFOLD:?set SAPIA_ACTIVATE_COLABFOLD in your .env to a tool activation script}"
set -u
```

So `.env` itself holds only:

- global settings (`PROSAPIA_TOOLS_DIR`, `CONDA_PREFIX`);
- the `SAPIA_ACTIVATE_<NAME>` pointer to each tool's activation script;
- the few values prosapia reads at **submit time**, before any activation script runs (these can't live in an activation script — see each tool below). #TODO make this values arguments of the run script

## Binding a tool

**1. Create your `.env`.**

```bash
cp .env.example .env
$EDITOR .env
```

**2. Write the tool's activation script.** Runnable templates for every tool live in [`examples/activation/`](../examples/activation/). Copy one and edit the paths:

```bash
cp examples/activation/rfdiffusion.sh /shared/lab/activation/rfdiffusion.sh
$EDITOR /shared/lab/activation/rfdiffusion.sh
```

There are two ways an activation script makes a tool available:

1. **Activate an environment** — the common case: activate a conda env / load a module, then export the tool's input paths.
2. **Point straight at an interpreter/binary.** Some tools take an optional path variable that defaults to a command on `PATH` — `RFDIFFUSION_PYTHON`, `PROTEIN_MPNN_PYTHON`, `USALIGN_BIN`, `PIPELINE_PYTHON`. Export it from the activation script when the binary isn't already on `PATH`.

An activation script is also the natural place for any per-tool runtime setup the job needs — pointing framework caches at node-local scratch, exporting extra env vars, etc.

**3. Point `SAPIA_ACTIVATE_<NAME>` at your script** in `.env`:

```bash
# in .env:
SAPIA_ACTIVATE_RFDIFFUSION="/shared/lab/activation/rfdiffusion.sh"
```

> [!NOTE] **Fork the tool** (`sapia fork-tool <name>`) and edit its `.sbatch` directly for changes deeper than activation and inputs.

### An example activation script

RFdiffusion's activation script ([`examples/activation/rfdiffusion.sh`](../examples/activation/rfdiffusion.sh)),
pointed at by `SAPIA_ACTIVATE_RFDIFFUSION` handles environment activation plus tool input declaration:

```bash
# activation
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or any command that puts conda on PATH
conda activate SE3nv

# tool input
export RUN_INFERENCE="/path/to/RFdiffusion/scripts/run_inference.py"
```

Then in `.env`:

```bash
CONDA_PREFIX="/path/to/miniconda3"
SAPIA_ACTIVATE_RFDIFFUSION="/shared/lab/activation/rfdiffusion.sh"
```

## Global settings

| Variable | Required | Meaning |
| --- | --- | --- |
| `PROSAPIA_TOOLS_DIR` | no | Extra directories to load custom tools from, `os.pathsep`-separated. Default `./tools`. See [Tool discovery](#tool-discovery-and-sharing). |
| `CONDA_PREFIX` | no | Conda base prefix, for activation scripts that source `"$CONDA_PREFIX/etc/profile.d/conda.sh"`. |

## Tool reference

Each tool below shows the `SAPIA_ACTIVATE_*` variable to set, the template to start from, and the variables it reads. The **Where** column says where each variable goes: in the tool's **activation script**, or directly in **`.env`** (the submit-time values, read before any activation script runs).

### RFdiffusion — `SAPIA_ACTIVATE_RFDIFFUSION`

Template: `examples/activation/rfdiffusion.sh`.

| Variable | Where | Required | Meaning |
| --- | --- | --- | --- |
| `RUN_INFERENCE` | activation script | yes | Path to RFdiffusion's `scripts/run_inference.py`. |
| `RFDIFFUSION_PYTHON` | activation script | no | Interpreter with RFdiffusion's deps. Defaults to `python`. |

### RFdiffusion3 / foundry — `SAPIA_ACTIVATE_RFDIFFUSION3`

Template: `examples/activation/rfdiffusion3.sh`. Do `conda activate <env>` and `export FOUNDRY_CHECKPOINT_DIRS=…` there; the sbatch then calls `rfd3`.

| Variable | Where | Required | Meaning |
| --- | --- | --- | --- |
| `RFD3_CKPT` | `.env` (submit time) | no | Explicit checkpoint override. Optional — foundry auto-discovers checkpoints after `foundry install rfd3`. #TODO make it an arg instead |

### ProteinMPNN — `SAPIA_ACTIVATE_MPNN_SEQS`

Template: `examples/activation/mpnn.sh`. Activate env and point `PROTEIN_MPNN` to the install path. The sbatch calls its scripts from there.

| Variable | Where | Required | Meaning |
| --- | --- | --- | --- |
| `PROTEIN_MPNN` | activation script | yes | Path to the ProteinMPNN install (its scripts are run from here). |
| `PROTEIN_MPNN_PYTHON` | activation script | no | Interpreter able to run ProteinMPNN. Defaults to `python`. |

### AlphaFold3 — `SAPIA_ACTIVATE_ALPHAFOLD3`

Template: `examples/activation/alphafold3.sh`. Put module setup (`ml purge`, `module load singularity`) there; the sbatch runs `singularity exec … "$AF3_CONTAINER"`.

| Variable | Where | Required | Meaning |
| --- | --- | --- | --- |
| `AF3_CONTAINER` | activation script | yes | AlphaFold3 container image (`.sif`). |
| `AF3_PARAMETERS` | activation script | yes | Model parameters directory (bound to `/root/models`). |
| `AF3_DATABASE` | activation script | yes | Public databases directory (bound to `/root/public_databases`). |

### ColabFold — `SAPIA_ACTIVATE_COLABFOLD`

Template: `examples/activation/colabfold.sh`. Activation script must put `colabfold_batch` on `PATH`.

### OpenFold3 — `SAPIA_ACTIVATE_OPENFOLD3`

Template: `examples/activation/openfold3.sh`. Activation script must put `run_openfold` on `PATH`.

### Boltz — `SAPIA_ACTIVATE_BOLTZ`

Template `examples/activation/boltz.sh`. Activation script must put `boltz` on `PATH`. The template also shows the optional framework-cache setup in the sbatch.

| Variable | Where | Required | Meaning |
| --- | --- | --- | --- |
| `USE_MSA` | `.env` (submit time) | no | `true` to run with an MSA; otherwise an empty MSA is used. |
| `TEMPLATE_CIF` | `.env` (submit time) | no | Path to a template CIF, if templating. |
| `TEMPLATE_THRESHOLD` | `.env` (submit time) | no | Template distance threshold (default `2.0`). |

### USalign — `SAPIA_ACTIVATE_USALIGN`

Template: `examples/activation/usalign.sh`.

| Variable | Where | Required | Meaning |
| --- | --- | --- | --- |
| `USALIGN_BIN` | activation script | no | Path to the `USalign` binary. Defaults to `USalign` on `PATH`. |

### Rosetta — `SAPIA_ACTIVATE_RELAXED` (rosetta_relax), `SAPIA_ACTIVATE_SYMMDEF` (make_symmdef)

One template serves both: `examples/activation/rosetta.sh`; point both variables at your copy.

| Variable | Where | Required | Meaning |
| --- | --- | --- | --- |
| `ROSETTA` | activation script | yes | Rosetta install root (the sbatch calls `$ROSETTA/bin/rosetta_scripts…` and `$ROSETTA/src/…`). |

### align_symm_axis — `SAPIA_ACTIVATE_ALIGN_SYMM_AXIS`

Template: `examples/activation/align_symm_axis.sh`.

| Variable | Where | Required | Meaning |
| --- | --- | --- | --- |
| `PIPELINE_PYTHON` | activation script | no | Interpreter for the per-task worker (needs prosapia + gemmi + numpy). Defaults to `python`. |

## Tool discovery and sharing

`sapia` discovers tools from the **built-in set first**, then from every directory
in `PROSAPIA_TOOLS_DIR`. Tools are keyed by the `name` in their `spec.py`, and
**later directories win**:

- a custom tool whose `name` matches a built-in **shadows** it;
- a new `name` registers **alongside** the built-ins.

Point `PROSAPIA_TOOLS_DIR` at a shared location so several prosapia environments
can reuse the same custom tools:

```bash
export PROSAPIA_TOOLS_DIR=/shared/lab/prosapia-tools:./tools
```

See [Writing a tool](writing-a-tool.md) for how a tool directory is laid out.
