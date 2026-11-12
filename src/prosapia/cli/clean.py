"""``sapia clean`` -- free the rows a campaign no longer needs.

``--filter`` / ``--where`` select the rows of a table to keep (the same meaning as on
``sapia run``) and every other row is cleaned: dropped from the table, with every
file under the table's leaves that belongs to it. ``--leaf`` narrows that to one
update leaf: the rows stay, the leaf's ``<leaf>_*`` cells are blanked and its files
for them go. ``--descendants`` also cleans the rows whose lineage runs through a
cleaned row (refused without it), ``--ancestors`` the parents a clean took the last
child of.

A file belongs to the designs its name points to (a row's name, or a parent's name
for all of its children) and to the rows whose cells name it; it goes once all of
them are cleaned. Clean is final: it appends what it removed to
``run_dir/.clean_log.jsonl``, which nothing reads back.

    sapia clean RUN_DIR -t table1 -w af3_pass=True --ancestors --dry-run
    sapia clean RUN_DIR -t table1 --leaf af3 -f keep_confident.py
"""

import json
import shutil
from argparse import ArgumentParser, Namespace
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..core.base_run import filter_rows
from ..core.data_manager import DataManager, RegistryManager
from ..core.executors import volume_path
from ..core.naming import PARENT_NAME, PARENT_TABLE, submission_dirs
from ..utils.cif_to_pdb import CACHE_DIRNAME
from .delete import is_create_leaf, leaf_columns

CLEAN_LOG = ".clean_log.jsonl"

# Characters that may follow a design's name in a file named after it.
_BOUNDARY = "._-"


class CleanArgs(Namespace):
    run_dir: Path
    table: str
    leaf: str | None
    filter: Path | None
    where: list[str] | None
    descendants: bool
    ancestors: bool
    dry_run: bool


@dataclass
class CleanPlan:
    """What a clean removes: rows dropped per table (``parents`` holds those
    ``--ancestors`` adds), cells blanked per table (``--leaf``), and files."""

    kept: tuple[int, int]  # (rows kept, rows in the table)
    rows: dict[str, list[str]] = field(default_factory=dict)
    parents: dict[str, list[str]] = field(default_factory=dict)
    cells: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)
    paths: list[Path] = field(default_factory=list)
    record: dict | None = None


def build_clean_parser() -> ArgumentParser:
    """Parent parser for the ``clean`` verb."""
    parser = ArgumentParser(add_help=False)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "-t",
        "--table",
        type=str,
        required=True,
        help="The table to clean (name, no extension).",
    )
    parser.add_argument(
        "--leaf",
        type=str,
        default=None,
        help="Only clean this update leaf's results (e.g. af3): the rows stay, its "
        "<leaf>_* cells are blanked and its files for them removed.",
    )
    parser.add_argument(
        "-f",
        "--filter",
        type=Path,
        default=None,
        help="A module defining apply_filter(df) -> df, as for sapia run. The rows it "
        "returns are kept and every other row is cleaned. It sees the table with its "
        "ancestors' columns.",
    )
    parser.add_argument(
        "-w",
        "--where",
        action="append",
        default=None,
        metavar="COL=VALUE",
        help="Like --filter: keep only rows whose COL equals VALUE (string compare) "
        "and clean the rest. Repeatable; applied after --filter.",
    )
    parser.add_argument(
        "--descendants",
        action="store_true",
        help="Also clean the rows of other tables whose lineage runs through a "
        "cleaned row (refused without it).",
    )
    parser.add_argument(
        "--ancestors",
        action="store_true",
        help="Also clean every parent row this clean took the last child of, up the "
        "lineage.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be removed and exit.",
    )
    return parser


def _is(frame: pd.DataFrame, names: list[str]) -> pd.Series:
    """Mask of ``frame``'s rows named in ``names`` (compared as strings)."""
    return frame.index.astype(str).isin(names) # type: ignore


def _blank(df: pd.DataFrame, rows: list[str], cols: list[str]) -> pd.DataFrame:
    """``df`` with ``cols`` emptied for ``rows`` (object dtype, so any column can
    hold NA; the TSV backend re-infers on read)."""
    df = df.copy()
    df[cols] = df[cols].astype(object)
    df.loc[_is(df, rows), cols] = pd.NA
    return df


def _links(frame: pd.DataFrame) -> list[tuple[str, str, str]]:
    """``(name, parent_table, parent_name)`` of every row with a parent link."""
    if PARENT_TABLE not in frame.columns or PARENT_NAME not in frame.columns:
        return []
    return [
        (str(n), str(pt), str(pn))
        for n, pt, pn in zip(frame.index, frame[PARENT_TABLE], frame[PARENT_NAME])
        if pd.notna(pt) and pd.notna(pn)
    ]


def _below(
    frames: dict[str, pd.DataFrame], gone: set[tuple[str, str]]
) -> dict[str, list[str]]:
    """Rows of any table whose lineage runs through a ``(table, name)`` in ``gone``,
    per table. Adds them to ``gone``."""
    found: dict[str, list[str]] = defaultdict(list)
    frontier = set(gone)
    while frontier:
        step = {
            (t, n)
            for t, frame in frames.items()
            for n, pt, pn in _links(frame)
            if (pt, pn) in frontier and (t, n) not in gone
        }
        for t, n in sorted(step):
            found[t].append(n)
        gone |= step
        frontier = step
    return dict(found)


def _orphaned(
    frames: dict[str, pd.DataFrame], gone: set[tuple[str, str]]
) -> dict[str, list[str]]:
    """Parent rows that ``gone`` takes the last child of (children in any table),
    then theirs, up the lineage, per table. A parent outside the registered tables
    (a root's) is never one. Adds them to ``gone``."""
    links = [(t, n, pt, pn) for t, f in frames.items() for n, pt, pn in _links(f)]
    names = {t: set(f.index.astype(str)) for t, f in frames.items()}
    found: dict[str, list[str]] = defaultdict(list)
    frontier = set(gone)
    while frontier:
        parents = {
            (pt, pn)
            for t, n, pt, pn in links
            if (t, n) in frontier and pn in names.get(pt, ())
        }
        alive = {(pt, pn) for t, n, pt, pn in links if (t, n) not in gone}
        step = parents - alive - gone
        for t, n in sorted(step):
            found[t].append(n)
        gone |= step
        frontier = step
    return dict(found)


def _as_path(value: object) -> Path | None:
    """A cell value naming an existing file or dir, in the runs-mount form."""
    if not isinstance(value, str) or "/" not in value:
        return None
    p = volume_path(value)
    return p if p.exists() or p.is_symlink() else None


def _refs(frame: pd.DataFrame, cache: Path) -> dict[Path, set[str]]:
    """Path -> the rows whose cells name it. A cached conversion under ``cache``
    also names the source its ``.src`` record holds."""
    refs: dict[Path, set[str]] = defaultdict(set)
    for name, row in frame.iterrows():
        for value in row:
            p = _as_path(value)
            if p is None:
                continue
            refs[p].add(str(name))
            src = p.with_suffix(".src")
            if p.is_relative_to(cache) and src.is_file():
                if (q := _as_path(src.read_text().strip())) is not None:
                    refs[q].add(str(name))
    return refs


def _base(name: str) -> str:
    """A file name without its extension (``x.cif.gz`` -> ``x``)."""
    return Path(name.removesuffix(".gz")).stem


def _keys(frame: pd.DataFrame, refs: dict[Path, set[str]]) -> dict[str, set[str]]:
    """Name -> the rows it points to: each row's name, each parent's name (all of
    its children), and each named file's base name (the rows naming it)."""
    keys: dict[str, set[str]] = defaultdict(set)
    for n in frame.index.astype(str):
        keys[n].add(n)
    if PARENT_NAME in frame.columns:
        for n, p in zip(frame.index.astype(str), frame[PARENT_NAME]):
            if isinstance(p, str) and p:
                keys[p].add(n)
    for p, rows in refs.items():
        keys[_base(p.name)] |= rows
    return keys


def _named(name: str, keys: dict[str, set[str]]) -> set[str]:
    """The rows the longest key that ``name`` is, or starts with followed by
    ``.``, ``_`` or ``-``, points to (``P_1`` never takes ``P_10.pdb``)."""
    cuts = [len(name)] + [
        i for i in range(len(name) - 1, 0, -1) if name[i] in _BOUNDARY
    ]
    for i in cuts:
        if name[:i] in keys:
            return keys[name[:i]]
    return set()


def _sweep(
    d: Path,
    refs: dict[Path, set[str]],
    keys: dict[str, set[str]],
    gone: set[str],
    protected: set[Path],
) -> tuple[list[Path], bool]:
    """The entries under ``d`` whose owners are all in ``gone``, and whether ``d``
    holds anything a remaining row owns. An owned dir holding nothing of a
    remaining row goes whole; otherwise only its owned entries go. Symlinks are
    never followed."""
    out: list[Path] = []
    held = False
    for e in sorted(d.iterdir()):
        owners = refs.get(e, set()) | _named(e.name, keys)
        mine = bool(owners) and owners <= gone
        e_held = e in protected or bool(owners - gone)
        if e.is_dir() and not e.is_symlink():
            inner, inner_held = _sweep(e, refs, keys, gone, protected)
            e_held = e_held or inner_held
            out += [e] if mine and not e_held else inner
        elif mine and not e_held:
            out.append(e)
        held = held or e_held
    return out, held


def _files(
    run_dir: Path,
    frame: pd.DataFrame,
    names: list[str],
    leaves: list[Path],
    cols: list[str] | None = None,
) -> list[Path]:
    """The files and dirs to remove when ``names`` leave ``frame``: dropped rows,
    or with ``cols`` only those cells blanked. Swept over ``leaves``' submission
    dirs, plus the cached conversions the cleaned cells name. Anything a remaining
    cell still names is kept."""
    cache = volume_path(run_dir / CACHE_DIRNAME)
    owned = frame if cols is None else frame[cols]
    after = frame[~_is(frame, names)] if cols is None else _blank(frame, names, cols)
    refs = _refs(owned, cache)
    protected = set(_refs(after, cache))
    keys = _keys(frame, refs)
    gone = set(names)

    out = []
    for p, rows in refs.items():
        if p.is_relative_to(cache) and rows <= gone and p not in protected:
            out += [q for q in (p, p.with_suffix(".src")) if q.exists()]
    for leaf in leaves:
        for sub in submission_dirs(leaf):
            out += _sweep(volume_path(sub), refs, keys, gone, protected)[0]
    return out


def plan_clean(
    run_dir: Path,
    registry: RegistryManager,
    table: str,
    leaf: str | None,
    filter_module: Path | None,
    where: list[str] | None,
    descendants: bool = False,
    ancestors: bool = False,
) -> CleanPlan:
    """Decide what keeping only the rows ``filter_module`` / ``where`` select of
    ``table`` removes. Pure; touches nothing."""
    if not filter_module and not where:
        raise SystemExit("clean needs --filter or --where: the rows to keep.")
    dm = registry.dm
    frames = {str(t): dm.read_frame(str(t)) for t in registry.get_registry().index}
    if table not in frames:
        raise SystemExit(f"No table {table!r} in {run_dir}.")
    leaf_dir = run_dir / table / leaf if leaf is not None else None
    if leaf_dir is not None:
        if not leaf_dir.is_dir():
            raise SystemExit(f"No leaf {leaf!r} under table {table!r}: {leaf_dir}")
        if is_create_leaf(leaf_dir, registry.get_table(table).tool_name):
            raise SystemExit(
                f"Leaf {leaf!r} created table {table!r}: to clean its rows, omit --leaf."
            )
        if descendants or ancestors:
            raise SystemExit(
                "--leaf keeps the rows, so --descendants / --ancestors don't apply."
            )

    df = frames[table]
    kept = filter_rows(dm, table, df, filter_module, where)
    names = [str(n) for n in df.index[~df.index.isin(kept.index)]]
    plan = CleanPlan(kept=(len(kept), len(df)))
    if not names:
        return plan

    if leaf_dir is not None:
        cols = leaf_columns(df, leaf_dir)
        if cols:
            plan.cells = {table: (names, cols)}
        plan.paths = _files(run_dir, df, names, [leaf_dir], cols)
        removed = {table: names}
    else:
        gone = {(table, n) for n in names}
        below = _below(frames, gone)
        if below and not descendants:
            raise SystemExit(
                f"Cleaning {len(names)} row(s) of {table!r} would orphan rows in "
                f"{', '.join(below)}. Pass --descendants to clean them too."
            )
        plan.rows = {table: names, **below}
        if ancestors:
            plan.parents = _orphaned(frames, gone)
        removed = {**plan.rows, **plan.parents}
        for t, rows in removed.items():
            t_dir = run_dir / t
            leaves = sorted(d for d in t_dir.glob("*") if d.is_dir())
            plan.paths += _files(run_dir, frames[t], rows, leaves)

    dirs = {p for p in plan.paths if p.is_dir() and not p.is_symlink()}
    plan.paths = sorted(
        {p for p in plan.paths if not any(d in dirs for d in p.parents)}
    )
    plan.record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "table": table,
        "leaf": leaf,
        "filter": str(filter_module) if filter_module else None,
        "where": where,
        "kept": len(kept),
        "removed": removed,
        "files": len(plan.paths),
    }
    return plan


def describe(plan: CleanPlan, table: str) -> list[str]:
    """One line per thing the plan removes."""
    n_kept, n_rows = plan.kept
    lines = [f"keep {n_kept} of {n_rows} row(s) of {table}"]
    if plan.record is None:
        return lines + ["nothing to clean"]
    lines += [f"drop {len(n)} row(s) from {t}" for t, n in plan.rows.items()]
    lines += [
        f"drop {len(n)} row(s) from {t} (left without children)"
        for t, n in plan.parents.items()
    ]
    for t, (names, cols) in plan.cells.items():
        lines.append(
            f"blank {len(cols)} column(s) for {len(names)} row(s) of {t}: "
            f"{', '.join(cols)}"
        )
    if plan.paths:
        lines.append(f"remove {len(plan.paths)} file(s)/dir(s)")
    lines.append(f"log to {CLEAN_LOG}")
    return lines


def apply(plan: CleanPlan, dm: DataManager, run_dir: Path) -> None:
    """Carry out ``plan``: table edits first, then the log, files last, so an
    interrupted clean never leaves cells pointing at removed files."""
    for t, names in [*plan.rows.items(), *plan.parents.items()]:
        frame = dm.read_frame(t)
        dm.write_frame(t, frame[~_is(frame, names)])
    for t, (names, cols) in plan.cells.items():
        dm.write_frame(t, _blank(dm.read_frame(t), names, cols))
    if plan.record is not None:
        with (run_dir / CLEAN_LOG).open("a") as log:
            log.write(json.dumps(plan.record) + "\n")
    for p in plan.paths:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink(missing_ok=True)


def clean_from_args(args: CleanArgs) -> None:
    """Dispatch for ``sapia clean``."""
    with DataManager(args.run_dir) as (dm, _, registry):
        plan = plan_clean(
            args.run_dir,
            registry,
            args.table,
            args.leaf,
            args.filter,
            args.where,
            args.descendants,
            args.ancestors,
        )
        prefix = "would " if args.dry_run else ""
        for line in describe(plan, args.table):
            print(prefix + line)
        if not args.dry_run:
            apply(plan, dm, args.run_dir)
