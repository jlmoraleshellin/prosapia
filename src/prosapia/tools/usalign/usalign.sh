#!/bin/bash
#SBATCH --cpus-per-task=4
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --job-name=usalign

# Run USalign on one design pair per array task and write a per-design TSV
# (name, status, pdb_a, pdb_b, sup_path, TM1..Lali) for collect_usalign.py.
# Inputs are already staged to PDB at manifest-build time.

set -uo pipefail

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_TASK_ID/SAPIA_LINE.
source "${SAPIA_PRELUDE:?}"

# Site-specific activation (required) — see docs/configuration.md.
sapia_activate SAPIA_ACTIVATE_USALIGN

NAME=$(echo "$SAPIA_LINE" | cut -f1)
PDB_A=$(echo "$SAPIA_LINE" | cut -f2)
PDB_B=$(echo "$SAPIA_LINE" | cut -f3)
COL_A=$(echo "$SAPIA_LINE" | cut -f4)
COL_B=$(echo "$SAPIA_LINE" | cut -f5)
PREFIX=$(echo "$SAPIA_LINE" | cut -f6)
MM=$(echo "$SAPIA_LINE" | cut -f7)
TER=$(echo "$SAPIA_LINE" | cut -f8)

USALIGN_BIN=${USALIGN_BIN:-USalign}
# 9 USalign metrics, in the order collect_usalign.py expects.
HEADER=$'name\tstatus\tpdb_a\tpdb_b\tsup_path\tTM1\tTM2\tRMSD\tID1\tID2\tIDali\tL1\tL2\tLali'

RESULTS_DIR="$OUT_DIR/$PREFIX"
mkdir -p "$RESULTS_DIR"
RESULT_TSV="$RESULTS_DIR/${NAME}.tsv"
SUP_PREFIX="$RESULTS_DIR/${NAME}"
SUP_PDB="${SUP_PREFIX}.pdb"

write_ok() {  # $1 = 9 tab-separated metric values
    printf '%s\n' "$HEADER" >"$RESULT_TSV"
    printf '%s\tOK\t%s\t%s\t%s\t%s\n' "$NAME" "$PDB_A" "$PDB_B" "$SUP_PDB" "$1" >>"$RESULT_TSV"
}
write_error() {  # $1 = message; pad the metric columns so the row stays rectangular
    printf '%s\n' "$HEADER" >"$RESULT_TSV"
    printf '%s\tERROR: %s\t\t\t\t\t\t\t\t\t\t\t\n' "$NAME" "$1" >>"$RESULT_TSV"
}

echo "[$(date +%T)] task $SAPIA_TASK_ID: comparing $NAME ($COL_A vs $COL_B)"

if [[ ! -f "$PDB_A" ]]; then write_error "missing: $PDB_A"; exit 0; fi
if [[ ! -f "$PDB_B" ]]; then write_error "missing: $PDB_B"; exit 0; fi

# Keep stderr out of $OUTPUT: USalign writes non-tabular chatter there even on
# success (with -o it always warns that only the last pair is superposed), and
# merging it into stdout used to make that warning look like the data line.
STDERR_FILE=$(mktemp)
if ! OUTPUT=$("$USALIGN_BIN" "$PDB_A" "$PDB_B" -mm "$MM" -ter "$TER" -outfmt 2 -o "$SUP_PREFIX" 2>"$STDERR_FILE"); then
    write_error "USalign failed: $(tr '\n' ' ' <"$STDERR_FILE")"
    rm -f "$STDERR_FILE"
    exit 0
fi
rm -f "$STDERR_FILE"

# -outfmt 2 prints a '#'-prefixed header then one data line. The first two
# fields are the input paths; fields 3-11 are the 9 metrics (matching the
# previous worker's fields[2:]). Select the data line by shape rather than by
# position -- the first non-header line carrying all 11 fields -- so any stray
# line cannot be mistaken for it.
DATA_LINE=$(printf '%s\n' "$OUTPUT" | awk -F'\t' '$0 !~ /^#/ && NF >= 11 { print; exit }')
if [[ -z "$DATA_LINE" ]]; then
    # Nothing usable: report the shape of the first real line, if there is one.
    FIRST_LINE=$(printf '%s\n' "$OUTPUT" | grep -v '^#' | grep -v '^[[:space:]]*$' | head -1)
    if [[ -z "$FIRST_LINE" ]]; then
        write_error "no data line in USalign output"
    else
        NF=$(printf '%s' "$FIRST_LINE" | awk -F'\t' '{print NF; exit}')
        write_error "expected 9 metrics, got $((NF - 2))"
    fi
    exit 0
fi

METRICS=$(printf '%s' "$DATA_LINE" | cut -f3-11)
write_ok "$METRICS"
