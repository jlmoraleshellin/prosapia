# Activation script for the `align_symm_axis` tool — point SAPIA_ACTIVATE_ALIGN_SYMM_AXIS here.
# Sourced by align_symm_axis.sbatch before it runs align_symm_axis_worker.py.
# Job: put a Python with prosapia + gemmi + numpy on PATH.

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate prosapia

# Optional: pin the interpreter explicitly instead of the activated env's `python`.
# export PIPELINE_PYTHON="/path/to/python"
