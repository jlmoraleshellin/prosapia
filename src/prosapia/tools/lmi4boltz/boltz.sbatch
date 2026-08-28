#!/bin/bash
#SBATCH --cpus-per-task=24
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --job-name=boltz

set -euo pipefail

set -a
source .env # Load CONDA_PREFIX and BOLTZ_ENV_NAME
set +a

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_LINE.
# Manifest line is tab-separated: shard_dir, devices.
source "${SAPIA_PRELUDE:?}"
SHARD_DIR=$(echo "$SAPIA_LINE" | cut -f1)
DEVICES=$(echo "$SAPIA_LINE" | cut -f2)

source "$CONDA_PREFIX/etc/profile.d/conda.sh"
conda activate "$BOLTZ_ENV_NAME"

export TRITON_CACHE_DIR="$SCRATCHDIR/triton_cache"
export PYTORCH_KERNEL_CACHE_PATH="$SCRATCHDIR/pytorch_kernel_cache"
mkdir -p "$TRITON_CACHE_DIR" "$PYTORCH_KERNEL_CACHE_PATH"


echo "[$(date +%T)] task $SLURM_ARRAY_TASK_ID: predicting shard $SHARD_DIR with $DEVICES device(s)"
boltz predict "$SHARD_DIR" \
    --out_dir "$OUT_DIR" \
    --devices "$DEVICES"
