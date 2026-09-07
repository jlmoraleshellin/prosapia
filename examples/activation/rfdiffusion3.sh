# Activation script for the `rfdiffusion3` tool — point SAPIA_ACTIVATE_RFDIFFUSION3 here.
# Sourced by rfdiffusion3.sbatch before it runs `rfd3 design`.
# Job: put `rfd3` on PATH and point foundry at its checkpoints.

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate foundry

# Where foundry looks for installed checkpoints (populated by `foundry install rfd3`).
export FOUNDRY_CHECKPOINT_DIRS="/path/to/foundry/checkpoints"

# Note: RFD3_CKPT (an explicit checkpoint override) is read by prosapia at submit
# time, before this script runs, so it lives in .env — not here.
