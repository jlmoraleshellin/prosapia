#!/bin/bash
#SBATCH --job-name=diffusion
#SBATCH --time=4:00:00
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G

set -uo pipefail
set -a
source .env # RFDIFFUSION_ENV, RUN_INFERENCE
set +a

MANIFEST=$1
OUTDIR=$2

# Each array task gets its own sub-manifest (one row per design). With
# --per-card N these N diffusions are launched together and time-share the
# task's single GPU. Rows are prepared at manifest-build time (tab-separated):
#   name  staged_input  output_prefix  contig  symmetry_token  global_extra
# symmetry_token and global_extra may be empty and may contain spaces, so fields
# are pulled with `cut` (which preserves empty fields, unlike `IFS=$'\t' read`).
SUBMANIFEST=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")

export HYDRA_FULL_ERROR=1

run_one() {
    local name=$1 staged=$2 prefix=$3 contig=$4 symmetry_token=$5 global_extra=$6
    local design_dir
    design_dir=$(dirname "$prefix")
    mkdir -p "$design_dir"

    # The tool injects only input/output/contigs; $global_extra (config flags +
    # optional overrides + --set) and $symmetry_token are intentionally unquoted
    # so their space-separated Hydra tokens each become a separate argv entry.
    # contigmap.contigs stays a single token (it may contain spaces).
    local cmd=(
        "$RFDIFFUSION_ENV" "$RUN_INFERENCE" $global_extra
    )
    # A root de-novo row carries an empty $staged: omit inference.input_pdb so
    # RFdiffusion generates from scratch. When set, keep it a single quoted token.
    [ -n "$staged" ] && cmd+=(inference.input_pdb="$staged")
    cmd+=(
        inference.output_prefix="$prefix"
        contigmap.contigs="$contig"
        $symmetry_token
    )

    "${cmd[@]}"
    local rc=$?

    # Plain-text marker read by collect_diffusion.py to confirm the task ran
    # (and record the exact command). Written whether or not diffusion succeeded.
    printf '%s\n' "${cmd[*]}" >"$design_dir/command.txt"

    return $rc
}

echo "Task ${SLURM_ARRAY_TASK_ID}: $(wc -l < "$SUBMANIFEST") diffusion(s) on one GPU"

pids=()
while IFS= read -r line || [ -n "$line" ]; do
    [ -z "$line" ] && continue
    name=$(printf '%s' "$line" | cut -f1)
    staged=$(printf '%s' "$line" | cut -f2)
    prefix=$(printf '%s' "$line" | cut -f3)
    contig=$(printf '%s' "$line" | cut -f4)
    symmetry_token=$(printf '%s' "$line" | cut -f5)
    global_extra=$(printf '%s' "$line" | cut -f6)
    echo "Launching $name"
    run_one "$name" "$staged" "$prefix" "$contig" "$symmetry_token" "$global_extra" &
    pids+=($!)
done < "$SUBMANIFEST"

fail=0
for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
done
exit $fail
