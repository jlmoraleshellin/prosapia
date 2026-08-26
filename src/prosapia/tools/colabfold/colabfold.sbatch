#!/bin/bash
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=04:00:00
#SBATCH --job-name=colabfold

set -a
source .env
set +a

set -euo pipefail

# Positional args from submit_sbatch_array:
#   $1 = manifest file (one column: fasta_path)
#   $2 = output dir (e.g. <run_dir>/colabfold)
MANIFEST=$1
OUT_DIR=$2

LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")
FASTA_PATH=$(echo "$LINE" | cut -f1)

set +u
source $COLABFOLD_ACTIVATE
set -u

TASK_OUT_DIR=$OUT_DIR/task_${SLURM_ARRAY_TASK_ID}
mkdir -p "$TASK_OUT_DIR"

echo "[$(date +%T)] task $SLURM_ARRAY_TASK_ID: predicting $FASTA_PATH"
colabfold_batch "$FASTA_PATH" "$TASK_OUT_DIR" \
    --model-type alphafold2_multimer_v3 \
    --msa-mode single_sequence \
    --num-relax 1
