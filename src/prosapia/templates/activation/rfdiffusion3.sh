# Activation script for the `rfdiffusion3` tool — point SAPIA_ACTIVATE_RFDIFFUSION3 here.
# Sourced by rfdiffusion3.sh before it runs `rfd3 design`.
# Job: put `rfd3` on PATH and point foundry at its checkpoints.

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate foundry

# Where foundry looks for installed checkpoints (populated by `foundry install rfd3`).
export FOUNDRY_CHECKPOINT_DIRS="/path/to/foundry/checkpoints"

# Optional: pin the checkpoint explicitly. rfdiffusion3.sh reads RFD3_CKPT at task time, after
# this script has run, and passes it to rfd3 as `ckpt_path`. Leave it out to let foundry find the
# checkpoint through FOUNDRY_CHECKPOINT_DIRS.
# export RFD3_CKPT="/path/to/foundry/checkpoints/rfd3_latest.ckpt"