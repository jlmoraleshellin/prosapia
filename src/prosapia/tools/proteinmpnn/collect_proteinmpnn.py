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

Each row carries only ``parent_name``; ancestor values (diffused parent,
boltz metrics) are resolved on demand by walking the lineage with
``DataManager.lookup`` / ``trace_lineage``, so nothing is propagated here.

The db was reserved by the run script (``run_proteinmpnn_sbatch.py --db-label``),
so collect only fills it: pass that db as ``--database``. Its parent (read only,
to resolve lineage) comes from the registry, so there is no ``--parent-db`` flag.

Usage:
    # Round 1 (after diffusion -> mpnn); db reserved as e.g. db1_<label>_mpnn_seqs:
    sapia collect mpnn_seqs outputs/20260430_170523_grow_hairpin_nofilter \\
        --database db1_<label>_mpnn_seqs

    # Round 2 (after boltz -> mpnn):
    sapia collect mpnn_seqs outputs/20260430_170523_grow_hairpin_nofilter \\
        --database db2_<label>_mpnn_seqs_r2
"""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd

from prosapia.core import (
    Collected,
    CollectCtx,
    CollectEach,
    DesignCtx,
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


def collect_mpnn(ctx: CollectCtx) -> CollectEach:
    """Per-parent ProteinMPNN collector. mpnn is a create tool: the framework iterates
    the ready parents and this mints one child row (``<parent>_f<i>``) per sampled
    sequence, carrying ``parent`` for lineage. The framework stamps status/path/
    parent_name from each Collected; child rows are discovered on disk, so re-running
    rebuilds them (idempotent)."""
    # Each grp_<g>/ output dir holds seqs/<design>.fa, where the staged input was
    # symlinked as <design>.pdb -- so the FASTA stem IS the parent-db row name.
    fasta_by_parent: Dict[str, Path] = {}
    for subdir in sorted(p for p in ctx.out_dir.iterdir() if p.is_dir()):
        if subdir.name in ("proteinmpnn_logs", "proteinmpnn_tasks"):
            continue
        seqs_dir = subdir / "seqs"
        if not seqs_dir.is_dir():
            continue
        for fasta_path in seqs_dir.glob("*.fa"):
            fasta_by_parent[fasta_path.stem] = fasta_path

    def one(d: DesignCtx) -> Iterable[Collected]:
        fasta_path = fasta_by_parent.get(d.name)
        if fasta_path is None:
            print(f"{d.name}: no FASTA found (skipping)")
            return

        for i, (header, sequence) in enumerate(parse_fasta(fasta_path)):
            # entries[0] is ProteinMPNN's echo of the native input sequence
            # (the old <parent>_f0). Skip it: only the sampled designs (_f1+)
            # are real outputs, so downstream predictors need no _f0 guard.
            if i == 0:
                continue

            data: Dict[str, Any] = {"iteration": i, "sequence": sequence}
            data.update(parse_mpnn_header(header))
            yield Collected(
                name=f"{d.name}_f{i}",
                parent=d.name,
                path=fasta_path,
                data=data,
            )

    return one
