# Activation script for the `colabfold` tool — point SAPIA_ACTIVATE_COLABFOLD here.
# Sourced by colabfold.sbatch before it runs `colabfold_batch`.
# Job: put `colabfold_batch` on PATH. Use whichever of these matches your install.

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate colabfold

# ...or an activate script shipped with a localcolabfold install:
# source /path/to/localcolabfold/activate.sh
