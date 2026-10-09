"""``sapia merge`` -- pool sibling tables into one new child table.

Forking the lineage (``--table-label``) or seeding several roots leaves parallel
same-gen tables, and every downstream tool then has to be run once per table.
``merge`` concatenates sibling tables into a new child of their shared parent so
the rest of the workflow runs once over the pooled designs.

    sapia merge RUN_DIR -t table1_worms_a table1_worms_b
    sapia merge RUN_DIR -t table0_x table0_y --table-label pooled

Rules:
  - every source must have the SAME parent table (roots merge with roots). The
    merged table is registered as an ordinary child of that parent, so lineage,
    ``lookup`` and later run/collect on it work unchanged;
  - sources are copied, not moved: rows keep their ``parent_table`` /
    ``parent_name`` / ``gen`` and every column, and the source tables stay as-is;
  - row names are suffixed with the source's distinguishing label (its registry
    label minus the parent's label prefix), e.g. ``S0_f0`` from ``table1_worms_a``
    under ``table0_worms`` becomes ``S0_f0_a``. An unlabelled source keeps bare
    names. The merge refuses if names still collide.

The merged table is named by the usual child rule (``table<gen>_<parent_label>_<label>``,
label ``merged`` by default) and recorded in the registry with ``tool=merge``; its
sources are listed in ``run_dir/<merged>/merge/.meta.json``. The merged table
name is the sole stdout line, so it can be captured.
"""

from argparse import Namespace, ArgumentParser
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..core.base_run import write_run_meta
from ..core.data_manager import DataManager, Table

MERGE_TOOL = "merge"

class MergeArgs(Namespace):
    run_dir: Path
    tables: list[str]
    table_label: str


def build_merge_parser() -> ArgumentParser:
    """Parent parser for the ``merge`` verb."""
    parser = ArgumentParser(add_help=False)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "-t",
        "--tables",
        nargs="+",
        required=True,
        help="Two or more source tables sharing the same parent table.",
    )
    parser.add_argument(
        "--table-label",
        type=str,
        default="merged",
        help="Label for the merged child table (append rule: "
        "table<gen>_<parent_label>_<table_label>). Defaults to 'merged'.",
    )
    return parser


def name_suffix(source: Table, parent_label: str) -> str:
    """The part of ``source``'s label that distinguishes it from its siblings."""
    label = source.table_label or ""
    if parent_label and label.startswith(f"{parent_label}_"):
        return label[len(parent_label) + 1 :]
    return label


def merge_from_args(args: MergeArgs) -> None:
    """Dispatch for ``sapia merge``: concat sibling tables into a new child table."""
    names = list(dict.fromkeys(args.tables))
    if len(names) < 2:
        raise SystemExit("merge needs at least two distinct source tables.")

    with DataManager(args.run_dir) as (dm, (read_frame, save_frame), registry):
        sources = [registry.get_table(n) for n in names]
        unregistered = [s.table_name for s in sources if s.gen is None]
        if unregistered:
            raise SystemExit(
                f"Table(s) not in registry: {', '.join(unregistered)}. "
                "Only registered tables can be merged."
            )

        parents = {s.parent_table_name for s in sources}
        if len(parents) > 1:
            listing = ", ".join(
                f"{s.table_name} <- {s.parent_table_name or 'root'}" for s in sources
            )
            raise SystemExit(
                "All sources must share the same parent table (merge siblings, or "
                f"merge their parents first). Got: {listing}."
            )
        parent = parents.pop()
        parent_label = (registry.get_table(parent).table_label or "") if parent else ""

        merged = registry.derive_new_table(parent, args.table_label)
        merged.tool_name = MERGE_TOOL
        if (
            merged.table_name in registry.get_registry().index
            or (args.run_dir / f"{merged.table_name}.tsv").exists()
        ):
            raise SystemExit(
                f"Table {merged.table_name!r} already exists; pass a different "
                "--table-label."
            )

        frames: list[pd.DataFrame] = []
        suffixes: dict[str, str] = {}
        for source in sources:
            df = read_frame(source.table_name)
            suffix = name_suffix(source, parent_label)
            suffixes[source.table_name] = suffix
            if suffix:
                df.index = pd.Index(
                    [f"{n}_{suffix}" for n in df.index], name=df.index.name
                )
            frames.append(df)

        df = pd.concat(frames)
        dup = df.index[df.index.duplicated()].unique()
        if len(dup):
            preview = ", ".join(map(str, dup[:5])) + (" ..." if len(dup) > 5 else "")
            raise SystemExit(
                f"{len(dup)} row name(s) collide after suffixing: {preview}. "
                "Rename the rows or merge from tables with distinct labels."
            )

        registry.register_table(merged)
        save_frame(merged.table_name, df)

        out_dir = args.run_dir / merged.table_name / MERGE_TOOL
        out_dir.mkdir(parents=True, exist_ok=True)
        write_run_meta(
            out_dir,
            tool=MERGE_TOOL,
            sources=[s.table_name for s in sources],
            suffixes=suffixes,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # Sole stdout line: the merged table name, so it can be captured.
    print(merged.table_name)
