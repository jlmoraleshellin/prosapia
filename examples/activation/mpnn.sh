# Activation script for the `mpnn_seqs` tool (ProteinMPNN) — point SAPIA_ACTIVATE_MPNN_SEQS here.
# Sourced by proteinmpnn.sbatch before it runs ProteinMPNN's scripts.
# Job: put a suitable Python on PATH and point at the ProteinMPNN checkout.

# --- activation (use whatever your site provides) ---
source "$CONDA_PREFIX/etc/profile.d/conda.sh" # or module load Minforge3 or similar
conda activate proteinmpnn

# ProteinMPNN checkout root; its helper_scripts/ and protein_mpnn_run.py live here (required).
export PROTEIN_MPNN="/path/to/ProteinMPNN"

# Optional: pin the interpreter explicitly instead of the activated env's `python`.
# export PROTEIN_MPNN_PYTHON="/path/to/python"
