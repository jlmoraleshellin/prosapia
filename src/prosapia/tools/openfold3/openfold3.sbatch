#!/bin/bash
#SBATCH --cpus-per-task=24
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --job-name=openfold3

set -a
source .env
set +a

set -euo pipefail

# Positional args from submit_sbatch_array:
#   $1 = manifest file (tab-separated: query_json, runner_yaml)
#   $2 = output dir (e.g. <run_dir>/openfold3)
MANIFEST=$1
OUT_DIR=$2

LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")
QUERY_JSON=$(echo "$LINE" | cut -f1)
RUNNER_YAML=$(echo "$LINE" | cut -f2)

set +u
source $OPENFOLD_ACTIVATE
set -u

TASK_OUT_DIR=$OUT_DIR/task_${SLURM_ARRAY_TASK_ID}
mkdir -p "$TASK_OUT_DIR"

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

echo "[$(date +%T)] task $SLURM_ARRAY_TASK_ID: predicting $QUERY_JSON"
run_openfold predict \
    --query-json "$QUERY_JSON" \
    --output-dir "$TASK_OUT_DIR" \
    --use-msa-server FALSE \
    --runner-yaml "$RUNNER_YAML"
