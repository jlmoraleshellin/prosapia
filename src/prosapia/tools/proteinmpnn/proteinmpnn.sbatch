#!/bin/bash
#SBATCH --job-name=proteinmpnn
#SBATCH --time=01:00:00
#SBATCH --partition=ampere_gpu,hopper_gpu
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=8G

set -euo pipefail

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_LINE.
source "${SAPIA_PRELUDE:?}"

# Site-specific activation (required) — see docs/configuration.md.
set +u
source "${SAPIA_ACTIVATE_MPNN_SEQS:?set SAPIA_ACTIVATE_MPNN_SEQS in your .env to a tool activation script}"
set -u

PROTEIN_MPNN_PYTHON=${PROTEIN_MPNN_PYTHON:-python}

# One array task = one sub-manifest listing the subgroups packed onto it. Each
# subgroup is a grp_<g>/ dir whose inputs/ holds symlinked PDBs that share params,
# so it runs as ONE batched protein_mpnn_run (model loaded once). Subgroups run
# sequentially on the task's single GPU. Sub-manifest rows are tab-separated:
#   grp_dir  chains  fixed_positions  tie_mode  tied_positions  mpnn_extra
# The single $chains list feeds every per-chain helper (--chain_list). chains,
# fixed_positions, tie_mode and tied_positions may be empty AND are adjacent, so
# fields are pulled with `cut` (IFS=$'\t' read collapses empty tab fields).
run_one_group() {
    local grp_dir=$1 chains=$2 fixed_positions=$3 tie_mode=$4
    local tied_positions=$5 mpnn_extra=$6

    local inputs="$grp_dir/inputs"
    local parsed="$grp_dir/parsed_pdbs.jsonl"
    local assigned="$grp_dir/assigned_pdbs.jsonl"
    local fixed="$grp_dir/fixed_pdbs.jsonl"
    local tied="$grp_dir/tied_pdbs.jsonl"

    echo "Task ${SLURM_ARRAY_TASK_ID}: $(basename "$grp_dir") ($(ls "$inputs" | wc -l) design(s))"

    "$PROTEIN_MPNN_PYTHON" "$PROTEIN_MPNN/helper_scripts/parse_multiple_chains.py" \
        --input_path="$inputs" --output_path="$parsed"

    # Optional side-input jsonls, each appended to the run only when produced. Every
    # per-chain helper shares the one $chains list as its --chain_list.
    local extra=()

    if [ -n "$chains" ]; then
        "$PROTEIN_MPNN_PYTHON" "$PROTEIN_MPNN/helper_scripts/assign_fixed_chains.py" \
            --input_path="$parsed" --output_path="$assigned" \
            --chain_list "$chains"
        extra+=(--chain_id_jsonl "$assigned")
    fi

    if [ -n "$fixed_positions" ]; then
        "$PROTEIN_MPNN_PYTHON" "$PROTEIN_MPNN/helper_scripts/make_fixed_positions_dict.py" \
            --input_path="$parsed" --output_path="$fixed" \
            --chain_list "$chains" --position_list "$fixed_positions"
        extra+=(--fixed_positions_jsonl "$fixed")
    fi

    # Tying: homo => --homooligomer 1 (all chains, auto-detected); explicit => per-chain
    # --chain_list/--position_list. --homooligomer defaults to 0, so it is never passed.
    if [ "$tie_mode" = "homo" ]; then
        "$PROTEIN_MPNN_PYTHON" "$PROTEIN_MPNN/helper_scripts/make_tied_positions_dict.py" \
            --input_path="$parsed" --output_path="$tied" --homooligomer 1
        extra+=(--tied_positions_jsonl "$tied")
    elif [ "$tie_mode" = "explicit" ]; then
        "$PROTEIN_MPNN_PYTHON" "$PROTEIN_MPNN/helper_scripts/make_tied_positions_dict.py" \
            --input_path="$parsed" --output_path="$tied" \
            --chain_list "$chains" --position_list "$tied_positions"
        extra+=(--tied_positions_jsonl "$tied")
    fi

    # $mpnn_extra (typed run flags + optional --bias_AA_jsonl + user --set tokens) is
    # unquoted so each space-separated token becomes its own argv entry. Outputs land
    # in $grp_dir/seqs/<design>.fa (one fasta per staged input).
    "$PROTEIN_MPNN_PYTHON" "$PROTEIN_MPNN/protein_mpnn_run.py" \
        --jsonl_path "$parsed" \
        --out_folder "$grp_dir" \
        $mpnn_extra \
        ${extra[@]+"${extra[@]}"}
}

SUBMANIFEST=$(printf '%s' "$SAPIA_LINE" | cut -f1)

while IFS= read -r row || [ -n "$row" ]; do
    [ -z "$row" ] && continue
    run_one_group \
        "$(printf '%s' "$row" | cut -f1)" \
        "$(printf '%s' "$row" | cut -f2)" \
        "$(printf '%s' "$row" | cut -f3)" \
        "$(printf '%s' "$row" | cut -f4)" \
        "$(printf '%s' "$row" | cut -f5)" \
        "$(printf '%s' "$row" | cut -f6)"
done < "$SUBMANIFEST"
