#!/bin/bash
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:15:00
#SBATCH --job-name=align_symm_axis

# Align one design's symmetric assembly onto RFdiffusion's +Z symmetry axis per
# array task, and write a per-design TSV (name, status, aligned_path, max_dev_deg)
# for collect_align_symm_axis.py to merge back. The worker needs pipeline_core +
# gemmi + numpy, so it runs under $PIPELINE_PYTHON (the pixi env interpreter).

set -euo pipefail
set -a
source .env  # optional PIPELINE_PYTHON override (pipeline pixi interpreter)
set +a

# Default to the repo-relative pixi env interpreter (cwd is the repo root), which
# carries pipeline_core + gemmi + numpy. Override via PIPELINE_PYTHON in .env.
PY=${PIPELINE_PYTHON:-.pixi/envs/default/bin/python}

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_LINE.
source "${SAPIA_PRELUDE:?}"
NAME=$(echo "$SAPIA_LINE" | cut -f1)
SYMM_PDB=$(echo "$SAPIA_LINE" | cut -f2)
SYMM_DEF=$(echo "$SAPIA_LINE" | cut -f3)

RESULT_TSV="$OUT_DIR/${NAME}.tsv"
OUT_PDB="$OUT_DIR/${NAME}_aligned.pdb"

echo "[$(date +%T)] task $SLURM_ARRAY_TASK_ID: align_symm_axis for $NAME"

# cwd is the repo root (SLURM inherits the submit dir; .env is sourced relatively),
# so the worker is addressed repo-root-relative. If the worker itself crashes
# (before it can record error-as-data), write a fallback error TSV so collect still
# sees this design.
if ! "$PY" tools/align_symm_axis/align_symm_axis_worker.py \
        --name "$NAME" \
        --symm-pdb "$SYMM_PDB" \
        --symm-def "$SYMM_DEF" \
        --out-pdb "$OUT_PDB" \
        --result-tsv "$RESULT_TSV"; then
    printf 'name\tstatus\taligned_path\tmax_dev_deg\n' >"$RESULT_TSV"
    printf '%s\terror: worker crashed\t\t\n' "$NAME" >>"$RESULT_TSV"
fi
