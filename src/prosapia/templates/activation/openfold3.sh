# Activation script for the `openfold3` tool — point SAPIA_ACTIVATE_OPENFOLD3 here.
# Sourced by openfold3.sbatch before it runs `run_openfold`.
# Job: put `run_openfold` on PATH.

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate openfold3

# ----site-specific runtime setup (optional) ---
# OpenFold's PyTorch extensions are large and slow to compile. Point
# TORCH_EXTENSIONS_DIR at a persistent path to cache the build across runs; left
# unset, PyTorch uses its default (~/.cache/torch_extensions).
# export TORCH_EXTENSIONS_DIR="/path/to/openfold_torch_extensions"
# Same with OpenFold's triton cache (~/.cache/torch_triton) and OPENFOLD_CACHE.
# Check Openfold3's documentation.
