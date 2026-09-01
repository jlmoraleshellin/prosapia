# PYTHON_ARGCOMPLETE_OK
"""Shared entry-point for every ``collect_*`` script.

A collect function stays pure (reads a ``CollectCtx``, returns row updates keyed by
name); all db mutation happens here. Given ``--database <db>``, it scans
``run_dir/<db>/<tool_leaf>/`` and writes rows into ``<db>.tsv``. ``Tool.action``
decides the contract: a create validates + stamps row lineage, an update only
writes rows back.
"""

from __future__ import annotations

import json
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar

import pandas as pd
from dotenv import load_dotenv

from .base_parser import base_parser
from .data_manager import Database, DataManager
from .naming import (
    GEN,
    PARENT_DB,
    PARENT_NAME,
    RUN_META_FILENAME,
    filter_ready,
    path_column,
    resolve_dir_name,
    status_column,
)

if TYPE_CHECKING:
    from .tool import ToolMetadata

load_dotenv()


# ARGS FUNCTION
class CollectArgs(Namespace):
    run_dir: Path
    database: str
    dir_label: str
    force: bool


AddArgsFn = Callable[[ArgumentParser], None]


# COLLECT FUNCTION
CollectResult = dict[str, dict[str, Any]]
LookupFn = Callable[[str, str], Any]
ArgsT = TypeVar("ArgsT", bound=CollectArgs)


@dataclass
class CollectCtx(Generic[ArgsT]):
    """Inputs a collect function may read (frame, args, dirs, cols, parent, lookup)."""

    df: pd.DataFrame
    args: ArgsT
    db_name: str
    out_dir: Path
    status_col: str
    path_col: str
    parent_db: str | None
    parent_df: pd.DataFrame
    lookup: LookupFn
    creates_db: bool
    default_input_column: str

    def _meta(self) -> dict | None:
        """The run's sidecar (``.meta.json``) for this out_dir, or None when
        absent (older run_dirs)."""
        p = self.out_dir / RUN_META_FILENAME
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    @property
    def ready(self) -> pd.DataFrame:
        """The designs to collect for: rows with a present input column.

        The input column is read from the run's sidecar; read from ``default_input_column`` when absent.
        The column lives in the source frame the run used: parent_db for a create tool, else this db.
        """
        meta = self._meta()
        col = (
            meta["input_column"]
            if meta and "input_column" in meta
            else self.default_input_column
        )
        frame = self.parent_df if self.creates_db else self.df
        return filter_ready(frame, col)


CollectFn = Callable[[CollectCtx[ArgsT]], CollectResult]


def _add_collect_args(parser: ArgumentParser) -> None:
    """Add the flags shared by every collector (``--dir-label`` + ``--force``).

    Collect takes no ``--input-column``: it reads the column the run recorded in the
    out_dir sidecar (see ``CollectCtx.ready``), so run and collect can't disagree.
    """
    parser.add_argument(
        "-l",
        "--dir-label",
        type=str,
        default="",
        help="Suffix of the tool output dir / column, for same-tool variants. "
        "Default is empty.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-collect rows that are already filled in.",
    )


def collect_argparser(description: str) -> ArgumentParser:
    """Parser shared by all collectors (``--database`` + ``--dir-label`` +
    ``--force``)."""
    parser = ArgumentParser(parents=[base_parser()], description=description)
    _add_collect_args(parser)
    return parser


def build_collect_parser(
    metadata: "ToolMetadata",
    add_extra_args_fn: AddArgsFn | None = None,
) -> ArgumentParser:
    """Build a reusable (``add_help=False``) parent parser holding every collect flag
    for a tool. Used by ``collect`` (standalone) and by the ``sapia`` CLI as
    ``parents=[...]`` of each ``collect <tool>`` subparser.
    """
    parser = ArgumentParser(add_help=False, parents=[base_parser()])
    _add_collect_args(parser)
    if add_extra_args_fn is not None:
        add_extra_args_fn(parser)
    return parser


def _finalize_create(
    updates: CollectResult,
    database: Database,
    parent_df: pd.DataFrame,
) -> None:
    """Stamp ``parent_db``/``gen`` on a create tool's rows and validate the parent edge."""
    if database.parent_db_name is not None:
        index = parent_df.index
        bad = [
            name
            for name, row in updates.items()
            if (p := row.get(PARENT_NAME)) is None or pd.isna(p) or p not in index
        ]
        if bad:
            preview = ", ".join(map(str, bad[:5])) + (" ..." if len(bad) > 5 else "")
            raise ValueError(
                f"{len(bad)} row(s) in create-collect for {database.db_name!r} are missing a "
                f"PARENT_NAME present in parent db {database.parent_db_name!r}: {preview}. Each "
                f"child-create row must set PARENT_NAME to a row in the parent db."
            )
        for row in updates.values():
            row[PARENT_DB] = database.parent_db_name
    else:
        # Root db (no parent): overwrite any PARENT_NAME with pd.NA
        for row in updates.values():
            row[PARENT_NAME] = pd.NA
    for row in updates.values():
        row.setdefault(GEN, database.gen)


def _finalize_update(
    updates: CollectResult, database: Database, df: pd.DataFrame
) -> None:
    """Warn (don't fail) when an update collect produces rows not already in the db."""
    new = [name for name in updates if name not in df.index]
    if new:
        preview = ", ".join(map(str, new[:5])) + (" ..." if len(new) > 5 else "")
        print(
            f"WARNING: update-collect for {database.db_name!r} produced {len(new)} row(s) not "
            f"already in the db: {preview}. An update annotates existing rows; if this "
            f"tool creates entities, declare it action='create'."
        )


def collect_from_args(
    metadata: ToolMetadata,
    collect_fn: CollectFn[ArgsT],
    args: ArgsT,
) -> None:
    """Execute a collect from already-parsed args (shared by standalone and ``sapia``)."""
    db_name = args.database

    with DataManager(args.run_dir) as (dm, (read_frame, save_frame), registry):
        # Get database and output directory name
        output_db = registry.get_database(db_name)
        out_dir = resolve_dir_name(args, output_db, metadata)

        # Read parent DataFrame or create one
        parent_df = (
            read_frame(output_db.parent_db_name)
            if output_db.parent_db_name
            else pd.DataFrame()
        )

        # Read source DataFrame
        df = read_frame(db_name)

        leaf = out_dir.name
        ctx = CollectCtx(
            df=df,
            args=args,
            db_name=db_name,
            out_dir=out_dir,
            status_col=status_column(leaf),
            path_col=path_column(leaf),
            parent_db=output_db.parent_db_name,
            parent_df=parent_df,
            lookup=partial(dm.lookup, df),
            creates_db=metadata.creates_db,
            default_input_column=metadata.default_input_column,
        )
        updates = collect_fn(ctx)

        if metadata.creates_db:
            _finalize_create(updates, output_db, parent_df)
        else:
            _finalize_update(updates, output_db, df)

        # Write updates
        for name, row in updates.items():
            df = dm.update(df, name, row)
        save_frame(db_name, df)

    print(f"Collected {len(updates)} row(s) into {db_name}.")
