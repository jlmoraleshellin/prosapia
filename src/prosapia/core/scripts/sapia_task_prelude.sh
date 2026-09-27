# sapia_task_prelude.sh — shared per-task scaffolding, scheduler-agnostic.
#
# Sourced by a tool's .sh via:  source "${SAPIA_PRELUDE:?}"
# (the executor exports SAPIA_PRELUDE into the task environment). Because it is
# sourced, it shares the caller's positional parameters ($1, $2) and runs in the
# same shell, so the variables and functions it defines are visible to the script.
#
# Provides:
#   .env            loaded (exported) so tool config + activation-script paths are available
#   MANIFEST        $1 — the tab-separated manifest for this submission
#   OUT_DIR         $2 — the tool's output directory
#   SAPIA_SCHEDULER the executor running this task (slurm | modal); defaults to slurm
#   SAPIA_TASK_ID   this task's 1-based manifest index (SLURM_ARRAY_TASK_ID under slurm)
#   SAPIA_LINE      this task's manifest line (tools cut their own fields)
#   sapia_activate  VAR — source the activation script named by $VAR (skipped under modal)

# Load the run's .env once, here, so tools don't each repeat it. cwd is the submit
# dir (the repo root), so this resolves the same .env the tools used to source.
set -a
[ -f .env ] && source .env
set +a

MANIFEST="${1:?sapia prelude: missing manifest arg (\$1)}"
OUT_DIR="${2:?sapia prelude: missing out_dir arg (\$2)}"

SAPIA_SCHEDULER="${SAPIA_SCHEDULER:-slurm}"
SAPIA_TASK_ID="${SAPIA_TASK_ID:-${SLURM_ARRAY_TASK_ID:?sapia prelude: no SAPIA_TASK_ID or SLURM_ARRAY_TASK_ID}}"

SAPIA_LINE="$(sed -n "${SAPIA_TASK_ID}p" "$MANIFEST")"

# Site-specific activation (see docs/configuration.md). Under modal the tool's
# image already provides the environment, so there is nothing to source.
sapia_activate() {
    local var=$1
    [ "$SAPIA_SCHEDULER" = "modal" ] && return 0
    if [ -z "${!var:-}" ]; then
        echo "sapia: set $var in your .env to a tool activation script" >&2
        return 1
    fi
    set +u
    source "${!var}"
    set -u
}
