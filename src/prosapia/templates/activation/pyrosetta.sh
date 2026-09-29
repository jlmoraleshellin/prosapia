# Activation script for the `pyrosetta` tool — point SAPIA_ACTIVATE_PYROSETTA here.
# Sourced by pyrosetta.sh before it runs pyrosetta_worker.py.
# Job: make a Python with `pyrosetta` importable.

# Either activate an env that has PyRosetta installed (use whatever your site provides)...
source "$CONDA_PREFIX/etc/profile.d/conda.sh"
conda activate pyrosetta

# ...or point PYROSETTA_PYTHON straight at that interpreter (defaults to `python` on PATH):
# export PYROSETTA_PYTHON="/path/to/envs/pyrosetta/bin/python"
