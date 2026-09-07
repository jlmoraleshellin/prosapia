#!/usr/bin/env python3
"""
Parse Rosetta score files and append metrics to the run database.

Usage:
    sapia collect relaxed outputs/20260416_155345_grow_hairpin --database db1_...
"""

from pathlib import Path
from typing import Dict, Iterable, Optional

from prosapia.core import Collected, CollectCtx, CollectEach, DesignCtx

# Metrics to extract from each score file. Add/remove as needed.
METRICS = [
    "total_score",
    "complex_normalized",
    "dG_separated",
    "dG_separated/dSASAx100",
    "dSASA_int",
    "delta_unsatHbonds",
    "fa_rep",
    "fa_atr",
    "hbonds_int",
    "packstat",
    "sc_value",
    "nres_int",
]


def parse_score_file(score_file: Path) -> Optional[Dict[str, float]]:
    """
    Parse a Rosetta .sc file. Returns averaged metrics across all SCORE data
    rows, or None if the file has no data rows.

    Rosetta score files are whitespace-separated with a header like:
        SCORE: total_score complex_normalized ... description
        SCORE:  -4136.565        -12.076      ... assembled_Slyse_1_..._0001
    """
    header: Optional[list[str]] = None
    rows: list[dict[str, str]] = []

    with open(score_file) as f:
        for line in f:
            if not line.startswith("SCORE:"):
                continue
            tokens = line.split()[1:]
            if header is None:
                header = tokens
            else:
                rows.append(dict(zip(header, tokens)))

    if header is None or not rows:
        return None

    out: dict[str, float] = {}
    for metric in METRICS:
        values: list[float] = []
        for row in rows:
            if metric in row:
                try:
                    values.append(float(row[metric]))
                except ValueError:
                    pass
        if values:
            out[metric] = sum(values) / len(values)
    return out


def collect_relax(ctx: CollectCtx) -> CollectEach:
    """Per-design Rosetta relax collector. The framework iterates ready designs and
    stamps status/path (keyed by the tool leaf); this locates one design's score file
    (+ relaxed PDB) and parses its metrics."""
    all_score_files = sorted(ctx.out_dir.glob("*_scores.sc"))
    all_pdb_files = sorted(ctx.out_dir.glob("*_0001.pdb"))
    print(f"Found {len(all_score_files)} score files, {len(all_pdb_files)} PDB files")

    def one(d: DesignCtx) -> Iterable[Collected]:
        score_file = next((f for f in all_score_files if d.name in f.name), None)
        if score_file is None:
            print(f"{d.name}: no score file")
            yield Collected(status="missing")
            return

        metrics = parse_score_file(score_file)
        if metrics is None:
            print(f"{d.name}: empty score file")
            yield Collected(status="empty")
            return

        pdb_file = next((f for f in all_pdb_files if d.name in f.name), None)
        data = {f"{d.leaf}_{k}": v for k, v in metrics.items()}
        print(
            f"{d.name}: dG_sep={metrics.get('dG_separated', float('nan')):7.2f}  "
            f"fa_rep={metrics.get('fa_rep', float('nan')):8.2f}  "
            f"total={metrics.get('total_score', float('nan')):9.2f}"
        )
        if pdb_file is None:
            print(f"{d.name}: scores parsed but no relaxed PDB found")
            yield Collected(status="OK_no_pdb", data=data)
        else:
            yield Collected(status="OK", path=pdb_file, data=data)

    return one
