"""On-demand CIF-to-PDB conversion with a shared cache under ``run_dir/.cif_to_pdb/``."""

import hashlib
from pathlib import Path

import gemmi


def ensure_pdb(src: Path, run_dir: Path) -> Path:
    """Return *src* as-is if already PDB, otherwise convert CIF -> PDB.

    Converted files are written to ``run_dir/.cif_to_pdb/<stem>.<digest>.pdb``,
    where ``<digest>`` derives from the resolved source path, digest helps to distinguish
    two different structures with the same stem . A sidecar ``.src``
    file records which source produced the cached PDB.
    """
    if src.suffix.lower() == ".pdb":
        return src

    cache_dir = run_dir / ".cif_to_pdb"
    digest = hashlib.sha1(str(src.resolve()).encode()).hexdigest()[:8]
    dst = cache_dir / f"{src.stem}.{digest}.pdb"
    src_record = dst.with_suffix(".src")

    if dst.exists() and src_record.exists():
        if src_record.read_text().strip() == str(src.resolve()):
            return dst

    cache_dir.mkdir(parents=True, exist_ok=True)
    structure = gemmi.read_structure(str(src))
    structure.setup_entities()
    structure.write_pdb(str(dst))
    src_record.write_text(str(src.resolve()))
    return dst
