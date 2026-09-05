# Activation script for the `USalign` tool — point SAPIA_ACTIVATE_USALIGN here.
# Sourced by usalign.sbatch before it runs USalign.
# Job: make the USalign binary available.

# Either put it on PATH (use whatever your site provides)...
module load usalign

# ...or point USALIGN_BIN straight at the binary (defaults to `USalign` on PATH):
# export USALIGN_BIN="/path/to/USalign"
