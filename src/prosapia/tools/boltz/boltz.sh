#!/bin/bash
#SBATCH --cpus-per-task=24
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --job-name=boltz

set -euo pipefail

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_LINE.
source "${SAPIA_PRELUDE:?}"

# Site-specific activation (required) — see docs/configuration.md.
# Must put `boltz` on PATH.
set +u
source "${SAPIA_ACTIVATE_BOLTZ:?set SAPIA_ACTIVATE_BOLTZ in your .env to a tool activation script}"
set -u

# Manifest columns (tab-separated):
#   shard_dir  extra
# $EXTRA holds every run-wide `boltz predict` option (--devices, --use_msa_server,
# ...) as space-separated tokens. It is intentionally left unquoted below so each
# token becomes its own argv entry.
SHARD_DIR=$(echo "$SAPIA_LINE" | cut -f1)
EXTRA=$(echo "$SAPIA_LINE" | cut -f2)

echo "[$(date +%T)] task $SLURM_ARRAY_TASK_ID: predicting shard $SHARD_DIR ($EXTRA)"
boltz predict "$SHARD_DIR" \
    --out_dir "$OUT_DIR" \
    $EXTRA
