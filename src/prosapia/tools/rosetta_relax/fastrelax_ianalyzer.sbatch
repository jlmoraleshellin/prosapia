#!/bin/bash
#SBATCH --job-name=slyB_relax
#SBATCH --time=4:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G

MANIFEST="$1"
OUTDIR="$2"

line=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")
input=$(echo "$line" | cut -f1)
symm=$(echo "$line" | cut -f2)
hairpin_length=$(echo "$line" | cut -f3)

name=$(basename "$input" _INPUT.pdb)
tmd_range=1-${hairpin_length}

if [ ! -f "$symm" ]; then
    echo "Missing symm file for $name"
    exit 1
fi

echo "Task $SLURM_ARRAY_TASK_ID: relaxing $name (tmd_range=$tmd_range)"

$ROSETTA/bin/rosetta_scripts.default.linuxgccrelease \
    -s "$input" \
    -parser:protocol tools/rosetta_relax/fastrelax_ianalyzer.xml \
    -parser:script_vars symmfile="$symm" \
    -nstruct 10 \
    -out:path:pdb "$OUTDIR/" \
    -out:file:scorefile "$OUTDIR/${name}_scores.sc"