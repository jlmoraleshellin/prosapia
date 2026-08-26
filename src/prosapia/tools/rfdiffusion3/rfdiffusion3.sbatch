#!/bin/bash
#SBATCH --job-name=rfdiffusion3
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G

set -uo pipefail
set -a
source .env # Load CONDA_PREFIX and FOUNDRY_ENV_NAME
set +a

# Positional args from submit_sbatch_array:
#   $1 = manifest file (tab-separated: shard_json \t rfd3_overrides)
#   $2 = output dir (e.g. <run_dir>/<db>/rfdiffusion3)
MANIFEST=$1
OUT_DIR=$2

LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")
SHARD_JSON=$(echo "$LINE" | cut -f1)
OVERRIDES=$(echo "$LINE" | cut -f2)

source "$CONDA_PREFIX/etc/profile.d/conda.sh"
conda activate "$FOUNDRY_ENV_NAME"
 export FOUNDRY_CHECKPOINT_DIRS="/data/groups/csb/anastassia.vorobieva/softwares/foundry"

SHARD_OUT_DIR=$OUT_DIR/results_$(basename "$SHARD_JSON" .json)
mkdir -p "$SHARD_OUT_DIR"

echo "[$(date +%T)] task $SLURM_ARRAY_TASK_ID: rfd3 design on $SHARD_JSON"
echo "  overrides: $OVERRIDES"

# OVERRIDES is intentionally unquoted: it is a space-separated list of Hydra
# key=value tokens that must each become a separate argv entry.
rfd3 design \
    inputs="$SHARD_JSON" \
    out_dir="$SHARD_OUT_DIR" \
    skip_existing=False \
    prevalidate_inputs=True \
    $OVERRIDES
