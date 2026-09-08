# Activation script for the `openfold3` tool — point SAPIA_ACTIVATE_OPENFOLD3 here.
# Sourced by openfold3.sbatch before it runs `run_openfold`.
# Job: put `run_openfold` on PATH and set TORCH_EXTENSIONS_DIR (the sbatch copies
# this persistent cache to node-local scratch before the run).

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate openfold3

# Persistent PyTorch-extensions build cache, kept on shared storage between runs.
export TORCH_EXTENSIONS_DIR="/path/to/openfold_torch_extensions"

# ----site-specific runtime setup (optional) ---
# Override the activation script's NFS paths with node-local ones
export TRITON_CACHE_DIR="$SCRATCHDIR/triton_cache"
export PYTHONUNBUFFERED=1
mkdir -p "$TRITON_CACHE_DIR"

# OpenFold's PyTorch extensions can be large and take a long time to compile, so we use a persistent cache directory on the NFS to speed up subsequent runs.
# We copy the cache to the node-local scratch for faster access during the run
PERSISTENT_CACHE=$TORCH_EXTENSIONS_DIR
export TORCH_EXTENSIONS_DIR=$SCRATCHDIR/openfold_cache

if [ -d "$PERSISTENT_CACHE" ]; then
  cp -r "$PERSISTENT_CACHE" "$TORCH_EXTENSIONS_DIR"
  # Defensive: nuke any locks that might have been copied. This is important because if a predicition is killed midrun while compiling an extension, the lock files can be left behind and cause subsequent runs to fail.
  find "$TORCH_EXTENSIONS_DIR" -name lock -delete 2>/dev/null || true
else
  mkdir -p "$TORCH_EXTENSIONS_DIR"
fi
