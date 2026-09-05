#!/bin/bash
#SBATCH --cpus-per-task=24
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --job-name=openfold3

set -euo pipefail

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_LINE.
# Manifest line is tab-separated: query_json, runner_yaml.
source "${SAPIA_PRELUDE:?}"

# Site-specific activation (required) — see docs/configuration.md.
# Must put `run_openfold` on PATH and set TORCH_EXTENSIONS_DIR.
set +u
source "${SAPIA_ACTIVATE_OPENFOLD3:?set SAPIA_ACTIVATE_OPENFOLD3 in your .env to a tool activation script}"
set -u

QUERY_JSON=$(echo "$SAPIA_LINE" | cut -f1)
RUNNER_YAML=$(echo "$SAPIA_LINE" | cut -f2)

TASK_OUT_DIR=$OUT_DIR/task_${SLURM_ARRAY_TASK_ID}
mkdir -p "$TASK_OUT_DIR"

echo "[$(date +%T)] task $SLURM_ARRAY_TASK_ID: predicting $QUERY_JSON"
run_openfold predict \
    --query-json "$QUERY_JSON" \
    --output-dir "$TASK_OUT_DIR" \
    --use-msa-server FALSE \
    --runner-yaml "$RUNNER_YAML"
