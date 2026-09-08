# Activation script for the `alphafold3` tool — point SAPIA_ACTIVATE_ALPHAFOLD3 here.
# Sourced by alphafold3.sbatch before it runs `singularity exec ... "$AF3_CONTAINER"`.
# Job: make `singularity` available and export the container + data locations.

# --- module setup (use whatever your site provides) ---
ml purge
module load singularity

# --- tool inputs (all required) ---
export AF3_CONTAINER="/path/to/alphafold3.sif"        # container image
export AF3_PARAMETERS="/path/to/af3/models"           # model params  (bound to /root/models)
export AF3_DATABASE="/path/to/af3/public_databases"   # public dbs    (bound to /root/public_databases)
