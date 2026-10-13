#!/bin/bash
#SBATCH --job-name=rfdiffusion3
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G

set -uo pipefail

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_TASK_ID/SAPIA_LINE. Our manifest line is a
# shard JSON (up to --shard-size design keys) plus the run-wide overrides. One
# `rfd3 design` process iterates the shard's keys in series on the single GPU.
source "${SAPIA_PRELUDE:?}"

# Site-specific activation (required) — see docs/configuration.md.
# Must put `rfd3` on PATH (e.g. `conda activate <env>` and export FOUNDRY_CHECKPOINT_DIRS).
# It may also `export RFD3_CKPT=/path/to/rfd3_latest.ckpt`; that is read just below, at task time.
sapia_activate SAPIA_ACTIVATE_RFDIFFUSION3

SHARD_JSON=$(echo "$SAPIA_LINE" | cut -f1)
OVERRIDES=$(echo "$SAPIA_LINE" | cut -f2)

# Checkpoint. Activation script sets RFD3_CKPT, so it is read here, AFTER activation. Unset (Modal, where the
# image's FOUNDRY_CHECKPOINT_DIRS=/checkpoints applies)
CKPT_ARG=()
CKPT_NOTE="not set: rfd3 resolves its own (FOUNDRY_CHECKPOINT_DIRS=${FOUNDRY_CHECKPOINT_DIRS:-unset})"
case " $OVERRIDES " in
    *ckpt_path=*) CKPT_NOTE="from the run's --set overrides (RFD3_CKPT ignored)" ;;
    *) if [ -n "${RFD3_CKPT:-}" ]; then
           CKPT_ARG=("ckpt_path=$RFD3_CKPT")
           CKPT_NOTE="$RFD3_CKPT (RFD3_CKPT)"
       fi ;;
esac

SHARD_OUT_DIR=$OUT_DIR/results_$(basename "$SHARD_JSON" .json)
mkdir -p "$SHARD_OUT_DIR"

echo "[$(date +%T)] task $SAPIA_TASK_ID: rfd3 design on $SHARD_JSON"
echo "  overrides: $OVERRIDES"
echo "  checkpoint: $CKPT_NOTE"

# OVERRIDES is intentionally unquoted: it is a space-separated list of Hydra
# key=value tokens that must each become a separate argv entry.
rfd3 design \
    inputs="$SHARD_JSON" \
    out_dir="$SHARD_OUT_DIR" \
    skip_existing=False \
    prevalidate_inputs=True \
    ${CKPT_ARG[@]+"${CKPT_ARG[@]}"} \
    $OVERRIDES
