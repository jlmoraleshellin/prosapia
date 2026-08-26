#!/bin/bash
#SBATCH --cpus-per-task=24
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --job-name=alphafold3

set -euo pipefail
set -a
source .env
set +a

# Positional args from submit_sbatch_array:
#   $1 = manifest file (tab-separated: shard_dir)
#   $2 = output dir (e.g. <run_dir>/alphafold3)
MANIFEST=$1
OUT_DIR=$2

LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")
SHARD_DIR=$(echo "$LINE" | cut -f1)
SHARD_OUT_DIR=$OUT_DIR/results_$(basename "$SHARD_DIR")
mkdir -p "$SHARD_OUT_DIR"

ml purge

echo "[$(date +%T)] task $SLURM_ARRAY_TASK_ID: predicting shard $SHARD_DIR"
singularity exec \
    --nv \
    --bind "$SHARD_DIR":/root/af_input \
    --bind "$SHARD_OUT_DIR":/root/af_output \
    --bind "$AF3_PARAMETERS":/root/models \
    --bind "$AF3_DATABASE":/root/public_databases \
    "$AF3_CONTAINER" \
    python /app/alphafold/run_alphafold.py \
    --input_dir=/root/af_input \
    --model_dir=/root/models \
    --db_dir=/root/public_databases \
    --output_dir=/root/af_output
