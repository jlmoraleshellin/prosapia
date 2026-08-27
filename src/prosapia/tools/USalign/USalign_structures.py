#!/usr/bin/env python3
"""Compare two predicted structures per design with USalign (TM-score, RMSD, alignment length).

For each row with both structure paths set, converts both to PDB via gemmi, runs
USalign in multi-chain mode, and writes the metrics plus the superposed-structure
path back to the db under ``<prefix>_*`` columns.

This is the per-design worker; the USalign tool drives it. Normally you run
``sapia run USalign`` (which submits the array) rather than calling this directly.

Usage (standalone, one db):
    pixi run python USalign_structures.py outputs/20260420_123035_grow_hairpin \
        --database mpnn_seqs_db --col-a boltz_path --col-b openfold3_path \
        [--output-prefix boltz_vs_openfold3]
"""

import argparse
import os
import subprocess
from pathlib import Path
from typing import cast

import gemmi
from prosapia.core import base_parser, DataManager

from dotenv import load_dotenv

load_dotenv()

USALIGN_BIN = os.getenv("USALIGN_BIN", "USalign")
USALIGN_COLUMNS = ["TM1", "TM2", "RMSD", "ID1", "ID2", "IDali", "L1", "L2", "Lali"]


def convert_to_pdb(src: Path, dst: Path) -> Path:
    """Convert any structure file to PDB using gemmi.

    Skips work if dst already exists and is at least as new as src.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    structure = gemmi.read_structure(str(src))
    structure.setup_entities()
    structure.write_pdb(str(dst))
    return dst


def run_usalign(path_a: Path, path_b: Path, sup_prefix: Path) -> dict[str, float]:
    """Run USalign and parse the -outfmt 2 output.

    Also writes superposed structures via -o <sup_prefix>. USalign creates
    <sup_prefix>.pdb, <sup_prefix>_all.pdb, <sup_prefix>_all_atm.pdb,
    <sup_prefix>_all_atm_lig.pdb and matching .pml scripts.
    """
    sup_prefix.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            USALIGN_BIN,
            str(path_a),
            str(path_b),
            "-mm",
            "1",
            "-ter",
            "0",
            "-outfmt",
            "2",
            "-o",
            str(sup_prefix),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"USalign failed: {result.stderr.strip()}")

    lines = result.stdout.strip().splitlines()
    data_line = None
    for line in lines:
        if not line.startswith("#"):
            data_line = line
            break

    if data_line is None:
        raise RuntimeError(f"No data line in USalign output:\n{result.stdout}")

    fields = data_line.split("\t")
    # First two fields are the PDBchain identifiers, metrics start at index 2.
    values = fields[2:]
    if len(values) < len(USALIGN_COLUMNS):
        raise RuntimeError(
            f"Expected {len(USALIGN_COLUMNS)} metrics, got {len(values)}: {data_line}"
        )

    return {col: float(values[i]) for i, col in enumerate(USALIGN_COLUMNS)}


class Args(argparse.Namespace):
    run_dir: Path
    database: str
    col_a: str
    col_b: str
    output_prefix: str | None
    usalign_bin: str


def main():
    parser = argparse.ArgumentParser(
        parents=[base_parser()],
        description="Compare two structures per design using USalign.",
    )
    parser.add_argument(
        "--col-a",
        type=str,
        required=True,
        help="Database column containing the path to structure A.",
    )
    parser.add_argument(
        "--col-b",
        type=str,
        required=True,
        help="Database column containing the path to structure B.",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=None,
        help="Prefix for output columns and PDB subdirectory. Defaults to "
        "'<col_a_stem>_vs_<col_b_stem>' (e.g. 'boltz_vs_openfold3').",
    )
    args = parser.parse_args(namespace=Args())

    db_name = args.database
    col_a = args.col_a
    col_b = args.col_b

    if args.output_prefix is not None:
        prefix = args.output_prefix
    else:
        stem_a = col_a.replace("_path", "")
        stem_b = col_b.replace("_path", "")
        prefix = f"{stem_a}_vs_{stem_b}"

    status_col = f"{prefix}_status"
    sup_path_col = f"{prefix}_sup_path"

    # All USalign-related output goes under <run_dir>/USalign/.
    # Converted PDBs are keyed by column name and shared across runs;
    # superpositions are specific to this comparison's prefix.
    usalign_root = args.run_dir / "USalign"
    out_dir_a = usalign_root / col_a
    out_dir_b = usalign_root / col_b
    sup_dir = usalign_root / prefix
    out_dir_a.mkdir(parents=True, exist_ok=True)
    out_dir_b.mkdir(parents=True, exist_ok=True)
    sup_dir.mkdir(parents=True, exist_ok=True)

    with DataManager(args.run_dir) as (dm, (read_frame, write_frame), _):
        df = read_frame(db_name)
        if df.empty:
            raise RuntimeError(f"Database {db_name!r} is empty or missing.")

        for col in (col_a, col_b):
            if col not in df.columns:
                raise RuntimeError(f"Column {col!r} not found in {db_name!r}.")

        ready = df[
            df[col_a].notna()
            & (df[col_a] != "")
            & df[col_b].notna()
            & (df[col_b] != "")
        ]

        print(f"Comparing {len(ready)} designs ({col_a} vs {col_b})")
        print(f"USalign outputs will be written under {usalign_root}")

        n_ok = 0
        n_err = 0
        for name in ready.index:
            name = cast(str, name)
            src_a = Path(str(ready.at[name, col_a]))
            src_b = Path(str(ready.at[name, col_b]))

            if not src_a.exists():
                df = dm.update(df, name, {status_col: f"missing: {src_a}"})
                write_frame(db_name, df)
                n_err += 1
                continue
            if not src_b.exists():
                df = dm.update(df, name, {status_col: f"missing: {src_b}"})
                write_frame(db_name, df)
                n_err += 1
                continue

            dst_a = out_dir_a / f"{name}.pdb"
            dst_b = out_dir_b / f"{name}.pdb"

            try:
                convert_to_pdb(src_a, dst_a)
                convert_to_pdb(src_b, dst_b)
            except Exception as e:
                df = dm.update(df, name, {status_col: f"ERROR: cif->pdb failed: {e}"})
                write_frame(db_name, df)
                n_err += 1
                continue

            try:
                sup_prefix = sup_dir / name
                metrics = run_usalign(dst_a, dst_b, sup_prefix)
                sup_pdb = sup_prefix.with_name(sup_prefix.name + ".pdb")
                row: dict[str, object] = {
                    status_col: "OK",
                    sup_path_col: str(sup_pdb),
                }
                row.update({f"{prefix}_{k}": v for k, v in metrics.items()})
                df = dm.update(df, name, row)
                n_ok += 1
            except Exception as e:
                df = dm.update(df, name, {status_col: f"ERROR: {e}"})
                n_err += 1

            write_frame(db_name, df)

    print(f"Done. ok={n_ok}, errors={n_err}")


if __name__ == "__main__":
    main()
