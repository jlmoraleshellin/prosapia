"""``sapia clean`` -- retire the designs a campaign no longer needs and free their files.

``--filter`` / ``--where`` select the rows of a table to keep (the same meaning as on
``sapia run``) and every other row is cleaned: its files under the table's leaves go,
every ``*_status`` of the row becomes ``cleaned`` and the cells naming a removed file
are emptied. The row, its lineage and its metrics stay, so the table remains the
record of what was cleaned. ``cleaned`` is final: run, collect and every downstream
tool skip the row from then on (see ``clean_ready``). ``--leaf`` frees only that
leaf's files and sets only its status; the row is retired all the same.
``--descendants`` also cleans the live rows whose lineage runs through a cleaned row
(refused without it), ``--ancestors`` the parents left with no live child.

A file belongs to the designs its name points to (a row's name, or a parent's name
for all of its children) and to the rows whose cells name it; it goes once all of
them are cleaned.

    sapia clean RUN_DIR -t table1 -w af3_pass=True --ancestors --dry-run
    sapia clean RUN_DIR -t table1 --leaf af3 -f keep_confident.py
"""

import shutil
from argparse import ArgumentParser, Namespace
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..core.base_run import filter_rows
from ..core.data_manager import DataManager, RegistryManager, cleaned_rows
from ..core.executors import volume_path
from ..core.naming import (
    CLEANED,
    PARENT_NAME,
    PARENT_TABLE,
    status_column,
    submission_dirs,
)
from ..utils.cif_to_pdb import CACHE_DIRNAME
from .delete import leaf_columns

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
    """What a clean does, per table: the rows it marks ``cleaned`` (``parents`` holds
    those ``--ancestors`` adds) and in which status columns, the ``(row, column)``
    cells it empties because the file they name goes; and the files it removes."""

    kept: tuple[int, int]  # (rows kept, rows in the table)
    rows: dict[str, list[str]] = field(default_factory=dict)
    parents: dict[str, list[str]] = field(default_factory=dict)
    status: dict[str, list[str]] = field(default_factory=dict)
    blank: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    paths: list[Path] = field(default_factory=list)


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
        help="Only free this leaf's files and set only its status (e.g. af3); the "
        "rows are retired all the same.",
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
        help="Also clean the live rows of other tables whose lineage runs through a "
        "cleaned row (refused without it).",
    )
    parser.add_argument(
        "--ancestors",
        action="store_true",
        help="Also clean every parent row left with no live child, up the lineage.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be cleaned and exit.",
    )
    return parser


def _is(frame: pd.DataFrame, names) -> pd.Series:
    """Mask of ``frame``'s rows named in ``names`` (compared as strings)."""
    return frame.index.astype(str).isin(list(names))  # type: ignore


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
    frames: dict[str, pd.DataFrame],
    start: set[tuple[str, str]],
    retired: dict[str, set[str]],
) -> dict[str, list[str]]:
    """The live rows of any table whose lineage runs through a ``(table, name)`` of
    ``start``, per table. Rows already retired are walked through, not returned."""
    found: dict[str, list[str]] = defaultdict(list)
    seen = set(start)
    frontier = set(start)
    while frontier:
        step = {
            (t, n)
            for t, frame in frames.items()
            for n, pt, pn in _links(frame)
            if (pt, pn) in frontier and (t, n) not in seen
        }
        for t, n in sorted(step):
            if n not in retired[t]:
                found[t].append(n)
        seen |= step
        frontier = step
    return dict(found)


def _orphaned(
    frames: dict[str, pd.DataFrame],
    start: set[tuple[str, str]],
    retired: dict[str, set[str]],
) -> dict[str, list[str]]:
    """The live parent rows left with no live child (in any table) once ``start`` is
    retired, then theirs, up the lineage, per table. A parent outside the registered
    tables (a root's) is never one."""
    links = [(t, n, pt, pn) for t, f in frames.items() for n, pt, pn in _links(f)]
    names = {t: set(f.index.astype(str)) for t, f in frames.items()}
    gone = {(t, n) for t, ns in retired.items() for n in ns} | start
    found: dict[str, list[str]] = defaultdict(list)
    frontier = set(start)
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
    """A cell value naming an existing file or dir, in the runs-mount form. Other
    strings with a ``/`` (a multi-chain sequence ``A/B``) name nothing, even when
    the OS can't stat them (a chain longer than a file name)."""
    if not isinstance(value, str) or "/" not in value:
        return None
    p = volume_path(value)
    try:
        return p if p.exists() or p.is_symlink() else None
    except OSError:
        return None


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
    gone: set[str],
    leaves: list[Path],
    cols: list[str] | None = None,
) -> list[Path]:
    """The files and dirs that belong only to the ``gone`` rows of ``frame`` (with
    ``cols``, only through those columns' cells): swept over ``leaves``' submission
    dirs, plus the cached conversions their cells name. Anything a live row's cell
    still names, or with ``cols`` any other column's, is kept."""
    cache = volume_path(run_dir / CACHE_DIRNAME)
    refs = _refs(frame if cols is None else frame[cols], cache)
    protected = set(_refs(frame[~_is(frame, gone)], cache))
    if cols is not None:
        protected |= set(_refs(frame.drop(columns=cols), cache))
    keys = _keys(frame, refs)

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
    ``table`` cleans. Pure; touches nothing."""
    if not filter_module and not where:
        raise SystemExit("clean needs --filter or --where: the rows to keep.")
    dm = registry.dm
    frames = {str(t): dm.read_frame(str(t)) for t in registry.get_registry().index}
    if table not in frames:
        raise SystemExit(f"No table {table!r} in {run_dir}.")
    leaf_dir = run_dir / table / leaf if leaf is not None else None
    if leaf_dir is not None and not leaf_dir.is_dir():
        raise SystemExit(f"No leaf {leaf!r} under table {table!r}: {leaf_dir}")

    retired = {t: set(cleaned_rows(f).astype(str)) for t, f in frames.items()}
    df = frames[table]
    kept = filter_rows(dm, table, df, filter_module, where)
    names = [
        str(n)
        for n in df.index[~df.index.isin(kept.index)]
        if str(n) not in retired[table]
    ]
    plan = CleanPlan(kept=(len(kept), len(df)))
    if not names:
        return plan

    start = {(table, n) for n in names}
    below = _below(frames, start, retired)
    if below and not descendants:
        raise SystemExit(
            f"Cleaning {len(names)} row(s) of {table!r} would leave live rows below "
            f"them in {', '.join(below)}. Pass --descendants to clean them too."
        )
    plan.rows = {table: names, **below}
    if ancestors:
        start |= {(t, n) for t, ns in below.items() for n in ns}
        plan.parents = _orphaned(frames, start, retired)

    for t, rows in [*plan.rows.items(), *plan.parents.items()]:
        frame, gone = frames[t], set(rows) | retired[t]
        if t == table and leaf_dir is not None:
            cols = leaf_columns(frame, leaf_dir)
            status = [c for c in cols if c.endswith("_status")]
            plan.status[t] = status or [status_column(leaf_dir.name)]
            plan.paths += _files(run_dir, frame, gone, [leaf_dir], cols)
        else:
            status = [c for c in frame.columns if str(c).endswith("_status")]
            tool = registry.get_table(t).tool_name or "clean"
            plan.status[t] = status or [status_column(tool)]
            leaves = sorted(d for d in (run_dir / t).glob("*") if d.is_dir())
            plan.paths += _files(run_dir, frame, gone, leaves)

    dirs = {p for p in plan.paths if p.is_dir() and not p.is_symlink()}
    plan.paths = sorted(
        {p for p in plan.paths if not any(d in dirs for d in p.parents)}
    )
    removed = set(plan.paths)
    for t, rows in [*plan.rows.items(), *plan.parents.items()]:
        frame = frames[t]
        cells = [
            (str(n), str(c))
            for n, row in frame[_is(frame, set(rows) | retired[t])].iterrows()
            for c, v in row.items()
            if (p := _as_path(v)) is not None
            and (p in removed or not removed.isdisjoint(p.parents))
        ]
        if cells:
            plan.blank[t] = cells
    return plan


def describe(plan: CleanPlan, table: str) -> list[str]:
    """One line per thing the plan does."""
    n_kept, n_rows = plan.kept
    lines = [f"keep {n_kept} of {n_rows} row(s) of {table}"]
    if not plan.rows:
        return lines + ["nothing to clean"]
    for t, names in plan.rows.items():
        cols = ", ".join(plan.status[t])
        lines.append(f"mark {len(names)} row(s) of {t} {CLEANED} ({cols})")
    for t, names in plan.parents.items():
        cols = ", ".join(plan.status[t])
        lines.append(
            f"mark {len(names)} row(s) of {t} {CLEANED}, left without children ({cols})"
        )
    if n_cells := sum(len(c) for c in plan.blank.values()):
        lines.append(f"empty {n_cells} cell(s) naming a removed file")
    if plan.paths:
        lines.append(f"remove {len(plan.paths)} file(s)/dir(s)")
    return lines


def _mark(
    frame: pd.DataFrame,
    names: list[str],
    status: list[str],
    blank: list[tuple[str, str]],
) -> pd.DataFrame:
    """``frame`` with ``status`` set to ``cleaned`` for ``names`` and the ``blank``
    cells emptied (object dtype, so any column can hold either; the TSV backend
    re-infers on read)."""
    frame = frame.copy()
    by_col: dict[str, list[str]] = defaultdict(list)
    for n, c in blank:
        by_col[c].append(n)
    for c in [*status, *by_col]:
        frame[c] = frame[c].astype(object) if c in frame.columns else pd.NA
    frame.loc[_is(frame, names), status] = CLEANED
    for c, rows in by_col.items():
        frame.loc[_is(frame, rows), c] = pd.NA
    return frame


def apply(plan: CleanPlan, dm: DataManager) -> None:
    """Carry out ``plan``: table edits first, files last, so an interrupted clean
    never leaves cells pointing at removed files."""
    for t, names in [*plan.rows.items(), *plan.parents.items()]:
        frame = _mark(dm.read_frame(t), names, plan.status[t], plan.blank.get(t, []))
        dm.write_frame(t, frame)
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
            apply(plan, dm)
