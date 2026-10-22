"""Resolving and sandboxing the file paths stored in a run's tables.

Tables hold paths as they were built when ``sapia`` ran: relative to that CWD
(``outputs/<run>/table1/leaf/x.pdb``) or absolute. A relative path is tried
against the run_dir and its parents; whatever it resolves to must live under the
run_dir or one of the extra ``--roots``.
"""

from pathlib import Path

STRUCTURE_SUFFIXES = (".pdb", ".cif", ".mmcif", ".ent", ".bcif")
TEXT_SUFFIXES = (
    ".out", ".err", ".exit", ".log", ".txt", ".fa", ".fasta",
    ".json", ".yaml", ".yml", ".csv", ".tsv", ".sh",
)


def strip_gz(name: str) -> tuple[str, bool]:
    lower = name.lower()
    return (lower[:-3], True) if lower.endswith(".gz") else (lower, False)


def is_structure(name: str) -> bool:
    return strip_gz(name)[0].endswith(STRUCTURE_SUFFIXES)


def is_text(name: str) -> bool:
    return strip_gz(name)[0].endswith(TEXT_SUFFIXES)


def structure_media_type(name: str) -> str:
    stem, _ = strip_gz(name)
    return "chemical/x-cif" if stem.endswith((".cif", ".mmcif", ".bcif")) else "chemical/x-pdb"


def candidate_bases(run_dir: Path) -> list[Path]:
    return list(dict.fromkeys([run_dir, *run_dir.parents[:3], Path.cwd()]))


def under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def resolve_safe_path(raw: str, run_dir: Path, roots: list[Path]) -> Path:
    """The file ``raw`` names, or ``FileNotFoundError`` when nothing matches and
    ``PermissionError`` when it only exists outside the allowed roots."""
    raw = raw.strip()
    if not raw:
        raise FileNotFoundError("empty path")
    p = Path(raw).expanduser()
    candidates = [p] if p.is_absolute() else [b / p for b in candidate_bases(run_dir)]
    allowed = [run_dir, *roots]
    outside = False
    for cand in candidates:
        if not cand.is_file():
            continue
        resolved = cand.resolve()
        if any(under(resolved, r) for r in allowed):
            return resolved
        outside = True
    if outside:
        raise PermissionError(f"path exists but is outside the served roots: {raw}")
    raise FileNotFoundError(f"path not found: {raw}")
