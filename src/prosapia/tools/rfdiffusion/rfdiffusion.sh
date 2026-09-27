#!/bin/bash
#SBATCH --job-name=diffusion
#SBATCH --time=4:00:00
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G

set -uo pipefail

# Shared scaffolding: sets MANIFEST/OUT_DIR/SAPIA_LINE. Our manifest line is a
# path to this task's sub-manifest (one row per design); output locations are
# baked into each design's output_prefix, so we never need OUT_DIR here.
source "${SAPIA_PRELUDE:?}"

# Site-specific activation (required) — see docs/configuration.md.
set +u
source "${SAPIA_ACTIVATE_RFDIFFUSION:?set SAPIA_ACTIVATE_RFDIFFUSION in your .env to a tool activation script}"
set -u

# Each array task gets its own sub-manifest (one row per design), prefixed with
# a lane index. Lanes (--per-card) run concurrently and time-share the task's
# single GPU; within a lane, rows (--shard-size) run in series. Rows are
# ACTIVATEd at manifest-build time (tab-separated):
#   lane  name  staged_input  output_prefix  contig  symmetry_token  global_extra
# symmetry_token and global_extra may be empty and may contain spaces, so fields
# are pulled with `cut` (which preserves empty fields, unlike `IFS=$'\t' read`).

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
    #
    # Two invocation shapes, selected by whether RFDIFFUSION_PYTHON is set:
    #   - unset (default): activate SE3nv (or otherwise put run_inference.py on
    #     PATH) and we run it directly as an executable. RUN_INFERENCE need not be
    #     set; it defaults to `run_inference.py`, resolved via PATH.
    #   - set: pin a specific interpreter to skip activation/module loading. Then
    #     RUN_INFERENCE MUST be an explicit path to run_inference.py, because
    #     `python <script>` resolves the script relative to cwd, not via PATH.
    local cmd=()
    if [ -n "${RFDIFFUSION_PYTHON:-}" ]; then
        cmd=( "$RFDIFFUSION_PYTHON" "${RUN_INFERENCE:?set RUN_INFERENCE to run_inference.py}" )
    else
        cmd=( "${RUN_INFERENCE:-run_inference.py}" )
    fi
    cmd+=( $global_extra )
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

    # Plain-text marker read by `sapia collect rfdiffusion` to confirm the task ran
    # (and record the exact command). Written whether or not diffusion succeeded.
    printf '%s\n' "${cmd[*]}" >"$design_dir/command.txt"

    return $rc
}

# Run one lane's rows in series. A failed design doesn't stop the lane; the lane
# exits non-zero if any of its designs failed.
run_lane() {
    local lane=$1 line rc=0
    local name staged prefix contig symmetry_token global_extra
    while IFS= read -r line || [ -n "$line" ]; do
        [ -z "$line" ] && continue
        name=$(printf '%s' "$line" | cut -f2)
        staged=$(printf '%s' "$line" | cut -f3)
        prefix=$(printf '%s' "$line" | cut -f4)
        contig=$(printf '%s' "$line" | cut -f5)
        symmetry_token=$(printf '%s' "$line" | cut -f6)
        global_extra=$(printf '%s' "$line" | cut -f7)
        echo "Lane $lane: launching $name"
        # </dev/null: keep run_inference.py from consuming the lane's remaining rows.
        run_one "$name" "$staged" "$prefix" "$contig" "$symmetry_token" "$global_extra" </dev/null || rc=1
    done < <(awk -F'\t' -v l="$lane" '$1 == l' "$SAPIA_LINE")
    return $rc
}

lanes=$(cut -f1 "$SAPIA_LINE" | sort -un)
echo "Task ${SLURM_ARRAY_TASK_ID}: $(wc -l < "$SAPIA_LINE") diffusion(s) in $(wc -w <<< "$lanes") lane(s) on one GPU"

pids=()
for lane in $lanes; do
    run_lane "$lane" &
    pids+=($!)
done

fail=0
for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
done
exit $fail
