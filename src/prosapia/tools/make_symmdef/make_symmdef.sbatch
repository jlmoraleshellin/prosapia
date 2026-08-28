#!/bin/bash
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --job-name=make_symmdef

# Run Rosetta's make_symmdef_file.pl on one design per array task, tidy up the
# extra files it drops next to the input PDB, and write a per-design TSV
# (name, status, symm_path) for collect_make_symmdef.py to merge back.

set -euo pipefail

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_LINE.
source "${SAPIA_PRELUDE:?}"

NAME=$(echo "$SAPIA_LINE" | cut -f1)
SRC=$(echo "$SAPIA_LINE" | cut -f2)

RESULT_TSV="$OUT_DIR/${NAME}.tsv"

write_result() {
    printf 'name\tstatus\tsymm_path\n' >"$RESULT_TSV"
    printf '%s\t%s\t%s\n' "$NAME" "$1" "$2" >>"$RESULT_TSV"
}

if [[ -z "${ROSETTA:-}" ]]; then
    echo "ROSETTA environment variable is not set" >&2
    write_result "error: ROSETTA not set" ""
    exit 1
fi
MAKESYMM="$ROSETTA/src/apps/public/symmetry/make_symmdef_file.pl"

if [[ ! -f "$SRC" ]]; then
    echo "MISSING: $SRC" >&2
    write_result "error: missing ($SRC)" ""
    exit 0
fi

STEM=$(basename "$SRC")
STEM=${STEM%.*}
SRC_DIR=$(dirname "$SRC")

echo "[$(date +%T)] task $SLURM_ARRAY_TASK_ID: make_symmdef for $NAME"

if perl "$MAKESYMM" -m NCS -a A -i B -p "$SRC" \
    >"$OUT_DIR/${STEM}.symm" 2>"$OUT_DIR/${STEM}.log"; then
    # The perl script writes extra files next to the input PDB. Move them.
    for suffix in _symm.pdb _INPUT.pdb; do
        LEFTOVER="$SRC_DIR/${STEM}${suffix}"
        if [[ -f "$LEFTOVER" ]]; then
            mv "$LEFTOVER" "$OUT_DIR/"
        fi
    done
    # _model_AB.pdb is garbage; delete it if present.
    rm -f "$SRC_DIR/${STEM}_model_AB.pdb"
    write_result "OK" "$OUT_DIR/${STEM}_symm.pdb"
else
    echo "make_symmdef_file.pl failed for $NAME" >&2
    write_result "error: make_symmdef_file.pl failed" ""
fi
