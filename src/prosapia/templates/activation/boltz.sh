# Activation script for the `boltz` tool — point SAPIA_ACTIVATE_BOLTZ here.
# Sourced by boltz.sbatch before it runs `boltz predict`.
# Job: put `boltz` on PATH, plus any site-specific runtime setup the job needs.

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate boltz

# --- site-specific runtime setup (optional) ---
# The activation script is also the perfect place for per-tool env tuning, e.g. setting cache path or pointing
# framework caches at node-local scratch.
export BOLTZ_CACHE="/path/to/boltz_cache"
export TRITON_CACHE_DIR="$SCRATCHDIR/triton_cache"
export PYTORCH_KERNEL_CACHE_PATH="$SCRATCHDIR/pytorch_kernel_cache"
mkdir -p "$TRITON_CACHE_DIR" "$PYTORCH_KERNEL_CACHE_PATH"
