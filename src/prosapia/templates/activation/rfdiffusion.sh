# Activation script for the `rfdiffusion` tool — point SAPIA_ACTIVATE_RFDIFFUSION here.
# Sourced by rfdiffusion.sbatch on the compute node, before it runs run_inference.py.
# Job: activate the conda environment and set the necessary paths.

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate SE3nv

# --- tool inputs ---
# Activating SE3nv above already puts run_inference.py on PATH, so RUN_INFERENCE
# is optional. Set it only if run_inference.py is not on PATH.
# export RUN_INFERENCE="/path/to/RFdiffusion/scripts/run_inference.py"

# Alternative to activation: pin the interpreter to skip conda/module loading.
# When set, RUN_INFERENCE above becomes REQUIRED — `python <script>` resolves the
# script by path, not via PATH.
# export RFDIFFUSION_PYTHON="/path/to/conda_envs/SE3nv/bin/python"
