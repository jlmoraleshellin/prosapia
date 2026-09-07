# Activation script for the Rosetta tools `relaxed` (rosetta_relax) and `symmdef`
# (make_symmdef). Point BOTH SAPIA_ACTIVATE_RELAXED and SAPIA_ACTIVATE_SYMMDEF here.
# Sourced before the sbatch calls $ROSETTA/bin/rosetta_scripts... and
# $ROSETTA/src/apps/public/symmetry/make_symmdef_file.pl.
# Job: make Rosetta (and perl, for make_symmdef) available and export the install root.

# --- module setup (use whatever your site provides) ---
module load rosetta
module load perl

# Rosetta install root; the sbatch calls $ROSETTA/bin/... and $ROSETTA/src/... (required).
export ROSETTA="/path/to/rosetta"
