#!/bin/bash
#SBATCH --cpus-per-task=24
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --job-name=alphafold3

set -euo pipefail

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_TASK_ID/SAPIA_LINE.
# Manifest line is tab-separated: shard_dir.
source "${SAPIA_PRELUDE:?}"

# Site-specific activation (required; e.g. `ml purge`, `module load singularity`) — see docs/configuration.md.
sapia_activate SAPIA_ACTIVATE_ALPHAFOLD3

SHARD_DIR=$(echo "$SAPIA_LINE" | cut -f1)
SHARD_OUT_DIR=$OUT_DIR/results_$(basename "$SHARD_DIR")
mkdir -p "$SHARD_OUT_DIR"

echo "[$(date +%T)] task $SAPIA_TASK_ID: predicting shard $SHARD_DIR"

# Under modal the task already runs inside the AF3 image, with params and databases
# mounted at /root/models and /root/public_databases (see modal_image.py), so
# run_alphafold.py is called directly instead of through singularity.
if [ "$SAPIA_SCHEDULER" = "modal" ]; then
    python /app/alphafold/run_alphafold.py \
        --input_dir="$SHARD_DIR" \
        --model_dir=/root/models \
        --db_dir=/root/public_databases \
        --output_dir="$SHARD_OUT_DIR"
else
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
fi
