"""``sapia delete`` -- remove a tool run: its leaf dir and what it wrote to the table.

A leaf lives under the table the tool wrote to, so there are two cases. An
``update`` leaf is ``run_dir/<table>/<leaf>/`` plus the ``<leaf>_*`` columns of
``<table>``: both go, the rest of the table stays. A ``create`` (or ``merge``) leaf
is the reason its table exists, so deleting it deletes the table: TSV, registry row
and ``run_dir/<table>/`` with every leaf inside. A table with descendants in the
registry is refused unless ``--recursive``.

    sapia delete RUN_DIR -t table1 --leaf proteinmpnn_seed2
    sapia delete RUN_DIR -t table1 --leaf proteinmpnn --recursive --dry-run
"""

import shutil
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..core.base_run import read_run_meta
from ..core.data_manager import REGISTRY_TABLE, DataManager, RegistryManager
from ..core.naming import PARENT_TABLE


class DeleteArgs(Namespace):
    run_dir: Path
    table: str
    leaf: str
    recursive: bool
    dry_run: bool


@dataclass
class DeletePlan:
    """What a delete removes: dirs on disk, whole tables (TSV + registry row), and
    columns per table."""

    dirs: list[Path] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    columns: dict[str, list[str]] = field(default_factory=dict)


def build_delete_parser() -> ArgumentParser:
    """Parent parser for the ``delete`` verb."""
    parser = ArgumentParser(add_help=False)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "-t",
        "--table",
        type=str,
        required=True,
        help="The table the leaf sits under (name, no extension): the table an "
        "update tool annotated, or the one a create tool made.",
    )
    parser.add_argument(
        "--leaf",
        type=str,
        required=True,
        help="The tool's leaf as written on disk and in column names, "
        "e.g. proteinmpnn or proteinmpnn_seed2 (tool[_dir_label]).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="When the leaf created its table, also delete every descendant table.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be removed and exit.",
    )
    return parser


def descendants(reg: pd.DataFrame, table: str) -> list[str]:
    """Every table below ``table`` in the registry, parents before children."""
    out: list[str] = []
    queue = [table]
    while queue:
        parent = queue.pop(0)
        if PARENT_TABLE not in reg.columns:
            break
        children = [str(n) for n in reg.index[reg[PARENT_TABLE] == parent]]
        out.extend(children)
        queue.extend(children)
    return out


def _is_create_leaf(leaf_dir: Path, table_tool: str | None) -> bool:
    """Whether ``leaf_dir`` is the run that created its table: the sidecar names the
    registry tool, or (no sidecar) the leaf is named after it."""
    if table_tool is None:
        return False
    tool = read_run_meta(leaf_dir).get("tool")
    if tool is not None:
        return tool == table_tool
    leaf = leaf_dir.name
    return leaf == table_tool or leaf.startswith(f"{table_tool}_")


def plan_delete(
    run_dir: Path,
    registry: RegistryManager,
    table: str,
    leaf: str,
    recursive: bool = False,
) -> DeletePlan:
    """Decide what deleting ``leaf`` under ``table`` removes. Pure; touches nothing."""
    leaf_dir = run_dir / table / leaf
    if not leaf_dir.is_dir():
        raise SystemExit(f"No leaf {leaf!r} under table {table!r}: {leaf_dir}")

    if _is_create_leaf(leaf_dir, registry.get_table(table).tool_name):
        below = descendants(registry.get_registry(), table)
        if below and not recursive:
            raise SystemExit(
                f"Leaf {leaf!r} created table {table!r}, which has descendant "
                f"table(s): {', '.join(below)}. Pass --recursive to delete them too."
            )
        tables = [table, *below]
        return DeletePlan(
            dirs=[run_dir / t for t in tables if (run_dir / t).is_dir()],
            tables=tables,
        )

    # Update leaf: its columns are ``<leaf>_*``, except those of a longer sibling
    # leaf (deleting ``proteinmpnn`` must keep ``proteinmpnn_seed2_status``).
    siblings = [
        d.name
        for d in leaf_dir.parent.iterdir()
        if d.is_dir() and d.name != leaf and d.name.startswith(f"{leaf}_")
    ]
    df = registry.dm.read_frame(table)
    cols = [
        c
        for c in df.columns
        if c.startswith(f"{leaf}_") and not any(c.startswith(f"{s}_") for s in siblings)
    ]
    return DeletePlan(dirs=[leaf_dir], columns={table: cols} if cols else {})


def describe(plan: DeletePlan, run_dir: Path) -> list[str]:
    """One line per thing the plan removes."""
    lines = [f"remove {d.relative_to(run_dir)}/" for d in plan.dirs]
    lines += [f"remove table {t} ({t}.tsv + registry row)" for t in plan.tables]
    for table, cols in plan.columns.items():
        lines.append(f"drop {len(cols)} column(s) from {table}: {', '.join(cols)}")
    return lines


def apply(plan: DeletePlan, dm: DataManager, run_dir: Path) -> None:
    """Carry out ``plan``: tables and columns first, dirs last, so an interrupted
    delete never leaves columns pointing at removed outputs."""
    if plan.tables:
        reg = dm.read_frame(REGISTRY_TABLE)
        dm.write_frame(REGISTRY_TABLE, reg.drop(index=plan.tables, errors="ignore"))
        for t in plan.tables:
            (run_dir / f"{t}.tsv").unlink(missing_ok=True)
    for table, cols in plan.columns.items():
        dm.write_frame(table, dm.read_frame(table).drop(columns=cols))
    for d in plan.dirs:
        shutil.rmtree(d)


def delete_from_args(args: DeleteArgs) -> None:
    """Dispatch for ``sapia delete``."""
    with DataManager(args.run_dir) as (dm, _, registry):
        plan = plan_delete(
            args.run_dir, registry, args.table, args.leaf, args.recursive
        )
        prefix = "would " if args.dry_run else ""
        for line in describe(plan, args.run_dir):
            print(prefix + line)
        if not args.dry_run:
            apply(plan, dm, args.run_dir)
