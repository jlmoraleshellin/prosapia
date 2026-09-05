# Activation script for the `rfdiffusion` tool — point SAPIA_ACTIVATE_RFDIFFUSION here.
# Sourced by rfdiffusion.sbatch on the compute node, before it runs run_inference.py.
# Job: activate the conda environment and set the necessary paths.

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate SE3nv

# --- tool inputs ---
# RFdiffusion's inference entrypoint (required).
export RUN_INFERENCE="/path/to/RFdiffusion/scripts/run_inference.py"

# Optional: pin the interpreter explicitly instead of the activated env's `python`.
# export RFDIFFUSION_PYTHON="/path/to/conda_envs/SE3nv/bin/python"
