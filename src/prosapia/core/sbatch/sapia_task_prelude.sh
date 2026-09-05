# sapia_task_prelude.sh — shared array-task scaffolding.
#
# Sourced by a tool's .sbatch via:  source "${SAPIA_PRELUDE:?}"
# (the `sapia` driver exports SAPIA_PRELUDE into the submit environment). Because
# it is sourced, it shares the caller's positional parameters ($1, $2) and runs
# in the same shell, so the variables it sets are visible to the rest of the script.
#
# Provides:
#   .env         loaded (exported) so tool config + Activation-hook paths are available
#   MANIFEST     $1 — the tab-separated manifest for this submission
#   OUT_DIR      $2 — the tool's output directory
#   SAPIA_LINE   this array task's manifest line (tools cut their own fields)

# Load the run's .env once, here, so tools don't each repeat it. cwd is the SLURM
# submit dir (the repo root), so this resolves the same .env the tools used to source.
set -a
[ -f .env ] && source .env
set +a

MANIFEST="${1:?sapia prelude: missing manifest arg (\$1)}"
OUT_DIR="${2:?sapia prelude: missing out_dir arg (\$2)}"

SAPIA_LINE="$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")"
