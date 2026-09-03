# Configuration

`prosapia` tools shell out to external binaries and environments (RFdiffusion,
ProteinMPNN, Rosetta, …). Their locations are supplied through **environment
variables**, loaded from a `.env` file in your working directory.

```bash
cp .env.example .env
$EDITOR .env
```

You only need to set the variables for the tools you actually run.

## Global settings

| Variable | Required | Meaning |
| --- | --- | --- |
| `PROSAPIA_TOOLS_DIR` | no | Extra directories to load custom tools from, `os.pathsep`-separated. Default `./tools`. See [Tool discovery](#tool-discovery-and-sharing). |
| `PIPELINE_PYTHON` | no | Interpreter for pipeline tools that run Python per array task (e.g. `align_symm_axis`). Defaults to the environment's own `python`. |

## Per-tool variables

### RFdiffusion — `rfdiffusion`

| Variable | Required | Meaning |
| --- | --- | --- |
| `RFDIFFUSION_ENV` | yes | Python interpreter of the RFdiffusion conda env (e.g. `SE3nv`). |
| `RUN_INFERENCE` | yes | Path to RFdiffusion's `scripts/run_inference.py`. |

### RFdiffusion3 / foundry — `rfdiffusion3`

| Variable | Required | Meaning |
| --- | --- | --- |
| `FOUNDRY_ENV_NAME` | yes | Conda env where `rc-foundry[rfd3]` is installed; the sbatch activates it and calls `rfd3` directly. |
| `RFD3_CKPT` | no | Explicit checkpoint path. Optional — foundry auto-discovers checkpoints after `foundry install rfd3`. |

### ProteinMPNN — `mpnn_seqs`

| Variable | Required | Meaning |
| --- | --- | --- |
| `PROTEIN_MPNN` | yes | Path to the ProteinMPNN install. |
| `PROTEIN_MPNN_PYTHON` | yes | Python interpreter able to run ProteinMPNN. |

### AlphaFold3 — `alphafold3`

| Variable | Required | Meaning |
| --- | --- | --- |
| `AF3_CONTAINER` | yes | AlphaFold3 container image (`.sif`). |
| `AF3_PARAMETERS` | yes | Model parameters directory (bound to `/root/models`). |
| `AF3_DATABASE` | yes | Public databases directory (bound to `/root/public_databases`). |

### ColabFold — `colabfold`

| Variable | Required | Meaning |
| --- | --- | --- |
| `COLABFOLD_ACTIVATE` | yes | Script sourced in the sbatch to activate the ColabFold environment. |

### OpenFold3 — `openfold3`

| Variable | Required | Meaning |
| --- | --- | --- |
| `OPENFOLD_ACTIVATE` | yes | Script sourced to activate the OpenFold3 environment. |

### Boltz — `lmi4boltz`

| Variable | Required | Meaning |
| --- | --- | --- |
| `BOLTZ_ENV_NAME` | yes | Conda env name the sbatch activates for Boltz. |
| `USE_MSA` | no | `true` to run with an MSA; otherwise an empty MSA is used. |
| `TEMPLATE_CIF` | no | Path to a template CIF, if templating. |
| `TEMPLATE_THRESHOLD` | no | Template distance threshold (default `2.0`). |

### USalign — `USalign`

| Variable | Required | Meaning |
| --- | --- | --- |
| `USALIGN_BIN` | yes | Path to the `USalign` binary. |

### Rosetta — `rosetta_relax`, `make_symmdef`

| Variable | Required | Meaning |
| --- | --- | --- |
| `ROSETTA` | yes | Rosetta install root (the sbatch calls `$ROSETTA/bin/rosetta_scripts…`). |
| `ROSETTASCRIPTS` | no | Override the `rosetta_scripts` binary if it differs from the default. |

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
