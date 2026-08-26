#!/usr/bin/env python3
"""
Collect ProteinMPNN FASTA outputs into a database.

Scans the output directory for per-design subdirectories, parses the FASTA
files produced by ProteinMPNN, and writes one row per designed sequence.

Lineage is derived from the directory structure:

    <output_dir>/grp_<g>/seqs/<fasta_stem>.fa

  * grp_<g>     = a batched subgroup run by proteinmpnn.sbatch (several designs
    sharing params, run in one protein_mpnn_run call).
  * fasta_stem  = the staged input filename ProteinMPNN processed. The submitter
    symlinks each input as ``<design_name>.pdb``, so the stem IS the immediate
    parent-db row -- stamped as ``parent_name``.

Each row carries only ``parent_name``; ancestor values (worms parent, diffused
parent, boltz metrics) are resolved on demand by walking the lineage with
``DataManager.lookup`` / ``trace_lineage``, so nothing is propagated here.

The db was reserved by the run script (``run_proteinmpnn_sbatch.py --db-label``),
so collect only fills it: pass that db as ``--database``. Its parent (read only,
to resolve lineage) comes from the registry, so there is no ``--parent-db`` flag.

Usage:
    # Round 1 (after diffusion -> mpnn); db reserved as e.g. db1_<label>_mpnn_seqs:
    python collect_proteinmpnn2.py outputs/20260430_170523_grow_hairpin_nofilter \\
        --database db1_<label>_mpnn_seqs

    # Round 2 (after boltz -> mpnn):
    python collect_proteinmpnn2.py outputs/20260430_170523_grow_hairpin_nofilter \\
        --database db2_<label>_mpnn_seqs_r2
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from prosapia.core import (
    PARENT_NAME,
    CollectCtx,
    CollectResult,
)

HEADER_FIELDS: Dict[str, type] = {
    "T": float,
    "sample": int,
    "score": float,
    "global_score": float,
    "seq_recovery": float,
}


def parse_mpnn_header(header: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {k: pd.NA for k in HEADER_FIELDS}
    for part in header.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in HEADER_FIELDS:
            try:
                out[key] = HEADER_FIELDS[key](value)
            except ValueError:
                out[key] = pd.NA
    return out


def parse_fasta(fasta_path: Path) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    header = ""
    seq_lines: List[str] = []
    with open(fasta_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if header:
                    entries.append((header, "".join(seq_lines)))
                header = line[1:]
                seq_lines = []
            else:
                seq_lines.append(line)
    if header:
        entries.append((header, "".join(seq_lines)))
    return entries


def collect_mpnn(ctx: CollectCtx) -> CollectResult:
    args, mpnn_dir = ctx.args, ctx.out_dir

    status_col = f"{mpnn_dir.name}_status"
    path_col = f"{mpnn_dir.name}_path"
    output_df = ctx.df

    # Each grp_<g>/ output dir holds seqs/<design>.fa, where the staged input was
    # symlinked as <design>.pdb -- so the FASTA stem IS the parent-db row name.
    subdirs = sorted(p for p in mpnn_dir.iterdir() if p.is_dir())
    print(f"Scanning {len(subdirs)} subdirectory(ies) in {mpnn_dir}")

    updates: CollectResult = {}
    n_rows = 0
    n_skipped = 0
    n_error = 0

    for subdir in subdirs:
        input_name = subdir.name
        seqs_dir = subdir / "seqs"

        if (
            subdir.name == "proteinmpnn_logs" or subdir.name == "proteinmpnn_tasks"
        ):  # Skip log  and tasks folder
            continue

        if not seqs_dir.is_dir():
            print(f"{input_name}: no seqs/ directory (skipping)")
            n_error += 1
            continue

        fastas = sorted(seqs_dir.glob("*.fa"))
        if not fastas:
            print(f"{input_name}: no .fa files in seqs/ (skipping)")
            n_error += 1
            continue

        for fasta_path in fastas:
            parent_name = fasta_path.stem
            entries = parse_fasta(fasta_path)

            for i, (header, sequence) in enumerate(entries):
                row_name = f"{parent_name}_f{i}"

                if (
                    not args.force
                    and status_col in output_df.columns
                    and row_name in output_df.index
                    and output_df.at[row_name, status_col] == "OK"
                ):
                    n_skipped += 1
                    continue

                row: Dict[str, Any] = {
                    PARENT_NAME: parent_name,  # immediate parent row in parent_db
                    "iteration": i,
                    status_col: "OK",
                    path_col: str(fasta_path),
                    "sequence": sequence,
                }
                row.update(parse_mpnn_header(header))

                updates[row_name] = row
                n_rows += 1

    skipped_msg = f", skipped={n_skipped}" if n_skipped else ""
    print(f"Done. wrote={n_rows}, errors={n_error}{skipped_msg}")
    return updates