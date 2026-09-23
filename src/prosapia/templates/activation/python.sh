# Activation script for the pure-Python tools, i.e. those that only need prosapia's
# own deps (gemmi, numpy, pandas): currently `align_symm_axis`. Point each such
# tool's SAPIA_ACTIVATE_<NAME> here (e.g. SAPIA_ACTIVATE_ALIGN_SYMM_AXIS).
# Sourced by the tool's sbatch before it runs its Python worker.
# Job: put a Python with prosapia + gemmi + numpy on PATH.

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate prosapia

# Optional: pin the interpreter explicitly instead of the activated env's `python`.
# export PIPELINE_PYTHON="/path/to/python"
