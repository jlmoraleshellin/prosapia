#!/usr/bin/env python3
"""
Align one design's symmetric assembly onto RFdiffusion's canonical +Z axis.

This is the per-array-task step of the align_symm_axis tool (and works standalone
for a single design). RFdiffusion symmetric motif scaffolding needs the motif's
cyclic (Cn) symmetry axis on +Z, centered at the origin: RFdiffusion auto-centers
motifs and propagates the asymmetric unit with fixed canonical rotation matrices
(cyclic axis = Z), so an input off that axis diffuses "in ways you don't intend."

The axis is read straight out of the Rosetta symmetry definition (.symm) file, not
inferred from coordinates. Each 'xyz VRT...' line carries that virtual residue's X
and Y unit vectors and its origin:

    xyz <name>  <X-unit-vector>  <Y-unit-vector>  <origin>

Adjacent subunit frames are related by rotation ABOUT the symmetry axis, so every
base-VRT frame shares the same Z = X x Y -- that cross product IS the Cn axis, and
the origin is a point on it (the center of rotation). Aligning onto +Z is then one
rigid transform: translate by -origin, then rotate (X x Y) onto (0, 0, 1). No atoms
are added, removed or re-symmetrized -- chains, numbering and each subunit's
internal coordinates are preserved.

Writes a one-row TSV (name, status, aligned_path, max_dev_deg) that
collect_align_symm_axis.py merges back into the database. Errors are recorded as
data (a status starting with 'error:') rather than only crashing, so partial array
runs still collect.

Usage (single design):
    pixi run python tools/align_symm_axis/align_symm_axis_worker.py \\
        --name foo --symm-pdb foo_symm.pdb --symm-def foo.symm \\
        --out-pdb foo_aligned.pdb --result-tsv foo.tsv
"""

import argparse
import csv
from pathlib import Path

import gemmi
import numpy as np


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-9:
        raise ValueError("zero-length vector")
    return v / n


def parse_symm_axis(symm_path: Path) -> tuple[np.ndarray, np.ndarray, float, int]:
    """Read the Cn symmetry axis and a point on it from a Rosetta .symm file.

    Returns ``(axis, origin, max_dev_deg, n_frames)`` where ``axis`` is the unit
    Cn axis (X x Y of the first VRT frame), ``origin`` is that frame's origin (a
    point on the axis), ``max_dev_deg`` is the largest angular disagreement of the
    per-frame axes (a consistency check -- should be ~0 for a clean Cn definition),
    and ``n_frames`` the number of VRT frames parsed.
    """
    frames: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for line in symm_path.read_text().splitlines():
        t = line.split()
        if len(t) >= 5 and t[0] == "xyz":
            try:
                X = np.array([float(v) for v in t[2].split(",")])
                Y = np.array([float(v) for v in t[3].split(",")])
                origin = np.array([float(v) for v in t[4].split(",")])
            except ValueError:
                continue
            if X.size == Y.size == origin.size == 3:
                frames.append((X, Y, origin))

    if not frames:
        raise ValueError(f"no 'xyz VRT' frames found in {symm_path}")

    X0, Y0, origin0 = frames[0]
    axis = _unit(np.cross(X0, Y0))

    # Every base-VRT frame should share the same Z axis; measure the spread.
    devs = [
        np.degrees(
            np.arccos(np.clip(abs(np.dot(axis, _unit(np.cross(X, Y)))), -1.0, 1.0))
        )
        for X, Y, _ in frames
    ]
    return axis, origin0, float(max(devs)), len(frames)


def _rotation_to_z(axis: np.ndarray) -> np.ndarray:
    """3x3 rotation mapping a unit vector onto +Z (Rodrigues)."""
    z = np.array([0.0, 0.0, 1.0])
    axis = _unit(axis)
    c = float(np.dot(axis, z))
    if c > 1.0 - 1e-9:
        return np.eye(3)  # already on +Z
    if c < -1.0 + 1e-9:
        return np.diag([1.0, -1.0, -1.0])  # antiparallel: 180 deg about X
    v = np.cross(axis, z)
    s = np.linalg.norm(v)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]], dtype=float)
    return np.eye(3) + vx + vx @ vx * ((1.0 - c) / (s * s))


def align_pdb(
    pdb_in: Path, pdb_out: Path, axis: np.ndarray, origin: np.ndarray
) -> None:
    """Write ``pdb_in`` to ``pdb_out`` rigidly moved so ``axis`` -> +Z, ``origin`` -> 0.

    The transform is ``x -> R * (x - origin)`` with ``R`` mapping the axis onto Z,
    applied to every atom in one pass.
    """
    structure = gemmi.read_structure(str(pdb_in))
    R = _rotation_to_z(axis)
    vec = -R @ origin

    tr = gemmi.Transform()
    tr.mat.fromlist(R.tolist())
    tr.vec.fromlist(vec.tolist())
    for model in structure:
        model.transform_pos_and_adp(tr)

    pdb_out.parent.mkdir(parents=True, exist_ok=True)
    structure.write_pdb(str(pdb_out))


def _write_result(
    result_tsv: Path, name: str, status: str, aligned_path: str, max_dev: str
) -> None:
    result_tsv.parent.mkdir(parents=True, exist_ok=True)
    with open(result_tsv, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["name", "status", "aligned_path", "max_dev_deg"])
        writer.writerow([name, status, aligned_path, max_dev])


class Args(argparse.Namespace):
    name: str
    symm_pdb: Path
    symm_def: Path
    out_pdb: Path
    result_tsv: Path


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Align one symmetric assembly onto RFdiffusion's +Z symmetry axis."
    )
    ap.add_argument("--name", required=True)
    ap.add_argument(
        "--symm-pdb", type=Path, required=True, help="Symmetric assembly PDB to align."
    )
    ap.add_argument(
        "--symm-def", type=Path, required=True, help="Rosetta .symm file (axis source)."
    )
    ap.add_argument("--out-pdb", type=Path, required=True, help="Aligned PDB to write.")
    ap.add_argument(
        "--result-tsv", type=Path, required=True, help="Per-design result TSV to write."
    )
    args = ap.parse_args(namespace=Args())

    try:
        if not args.symm_pdb.exists():
            raise FileNotFoundError(f"symmetric PDB missing: {args.symm_pdb}")
        if not args.symm_def.exists():
            raise FileNotFoundError(f".symm file missing: {args.symm_def}")

        axis, origin, max_dev, n_frames = parse_symm_axis(args.symm_def)
        align_pdb(args.symm_pdb, args.out_pdb, axis, origin)
        print(
            f"{args.name}: aligned ({n_frames} VRT frames, axis agreement "
            f"max dev {max_dev:.4f} deg) -> {args.out_pdb}"
        )
        _write_result(
            args.result_tsv, args.name, "OK", str(args.out_pdb), f"{max_dev:.6f}"
        )
    except Exception as e:
        print(f"{args.name}: ERROR {e}")
        _write_result(args.result_tsv, args.name, f"error: {e}", "", "")


if __name__ == "__main__":
    main()
