#!/bin/bash
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=01:00:00
#SBATCH --job-name=pyrosetta

# Score one design with PyRosetta per array task (optional FastRelax first) and
# write a per-design TSV (name, status, scored_path, metrics...) plus the scored
# PDB for collect_pyrosetta.py. The worker needs pyrosetta, so it runs under
# $PYROSETTA_PYTHON (defaulting to `python`).

set -euo pipefail

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_TASK_ID/SAPIA_LINE.
source "${SAPIA_PRELUDE:?}"

# Site-specific activation (required) — see docs/configuration.md.
sapia_activate SAPIA_ACTIVATE_PYROSETTA

PY=${PYROSETTA_PYTHON:-python}

NAME=$(echo "$SAPIA_LINE" | cut -f1)
PDB=$(echo "$SAPIA_LINE" | cut -f2)
RELAX_CYCLES=$(echo "$SAPIA_LINE" | cut -f3)
CONSTRAIN=$(echo "$SAPIA_LINE" | cut -f4)
INTERFACE=$(echo "$SAPIA_LINE" | cut -f5)
SCOREFXN=$(echo "$SAPIA_LINE" | cut -f6)

RESULT_TSV="$OUT_DIR/${NAME}.tsv"
OUT_PDB="$OUT_DIR/${NAME}.pdb"

echo "[$(date +%T)] task $SAPIA_TASK_ID: pyrosetta for $NAME (relax cycles $RELAX_CYCLES)"

EXTRA=()
[[ "$CONSTRAIN" == "1" ]] && EXTRA+=(--constrain-relax)
[[ -n "$INTERFACE" ]] && EXTRA+=(--interface "$INTERFACE")

# If the worker itself crashes (before it can record error-as-data), write a
# fallback error TSV so collect still sees this design.
if ! "$PY" "${SAPIA_TOOL_DIR:?}/pyrosetta_worker.py" \
        --name "$NAME" \
        --pdb "$PDB" \
        --relax-cycles "$RELAX_CYCLES" \
        --scorefxn "$SCOREFXN" \
        --out-pdb "$OUT_PDB" \
        --result-tsv "$RESULT_TSV" \
        "${EXTRA[@]}"; then
    printf 'name\tstatus\tscored_path\n' >"$RESULT_TSV"
    printf '%s\terror: worker crashed\t\n' "$NAME" >>"$RESULT_TSV"
fi
