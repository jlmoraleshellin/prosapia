#!/bin/bash
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=04:00:00
#SBATCH --job-name=colabfold

set -euo pipefail

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_TASK_ID/SAPIA_LINE.
# Manifest line is one column: fasta_path.
source "${SAPIA_PRELUDE:?}"

# Site-specific activation (required) — see docs/configuration.md.
sapia_activate SAPIA_ACTIVATE_COLABFOLD

FASTA_PATH=$(echo "$SAPIA_LINE" | cut -f1)

TASK_OUT_DIR=$OUT_DIR/task_${SAPIA_TASK_ID}
mkdir -p "$TASK_OUT_DIR"

echo "[$(date +%T)] task $SAPIA_TASK_ID: predicting $FASTA_PATH"
colabfold_batch "$FASTA_PATH" "$TASK_OUT_DIR" \
    --model-type alphafold2_multimer_v3 \
    --msa-mode single_sequence \
    --num-relax 1
