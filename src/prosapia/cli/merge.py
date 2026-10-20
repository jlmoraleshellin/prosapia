"""``sapia merge`` -- pool same-gen tables into one new table.

Siblings merge into a child of their shared parent; cousins get their parents
merged first (recursively) so every table keeps one parent; ``--lift`` pads a
shallower source with pass-through copies. Rows keep every column, get a
``merge_source`` column and a label-derived name suffix. Full rules and the
recommended workflow: ``docs/using-labels.md``.

    sapia merge RUN_DIR -t table1_worms_a table1_worms_b
    sapia merge RUN_DIR -t table0_x table0_y --table-label pooled
    sapia merge RUN_DIR -t table3_x_a table2_x_b --lift
"""

import json
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..core.base_run import write_run_meta
from ..core.data_manager import (
    BackendRead,
    BackendWrite,
    DataManager,
    RegistryManager,
    Table,
)
from ..core.naming import (
    GEN,
    MERGE_SOURCE,
    PARENT_NAME,
    PARENT_TABLE,
    RUN_META_FILENAME,
)

MERGE_TOOL = "merge"


class MergeArgs(Namespace):
    run_dir: Path
    tables: list[str]
    table_label: str
    lift: bool


@dataclass
class MergeCtx:
    run_dir: Path
    read_frame: BackendRead
    write_frame: BackendWrite
    registry: RegistryManager


def build_merge_parser() -> ArgumentParser:
    """Parent parser for the ``merge`` verb."""
    parser = ArgumentParser(add_help=False)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "-t",
        "--tables",
        nargs="+",
        required=True,
        help="Two or more source tables: siblings, cousins, or (with --lift) "
        "tables of different gens.",
    )
    parser.add_argument(
        "--table-label",
        type=str,
        default="merged",
        help="Label for the merged table (append rule: "
        "table<gen>_<parent_label>_<table_label>). Defaults to 'merged'.",
    )
    parser.add_argument(
        "--lift",
        action="store_true",
        help="Allow sources of different gens: pad the shallower lineage with "
        "pass-through copies up to the deepest gen.",
    )
    return parser


def own_label(table: Table, parent_label: str) -> str:
    """The part of ``table``'s label added on top of its parent's label."""
    label = table.table_label or ""
    if parent_label and label.startswith(f"{parent_label}_"):
        return label[len(parent_label) + 1 :]
    if label == parent_label:
        return ""
    return label


def _join(*parts: str) -> str:
    return "_".join(p for p in parts if p)


def _existing_merge(
    ctx: MergeCtx, name: str, source_names: list[str]
) -> dict[str, str] | None:
    """Suffix map of an existing merge of exactly ``source_names`` under ``name``;
    None when ``name`` is free. Raises when ``name`` is taken by anything else."""
    if (
        name not in ctx.registry.get_registry().index
        and not (ctx.run_dir / f"{name}.tsv").exists()
    ):
        return None
    meta_path = ctx.run_dir / name / MERGE_TOOL / RUN_META_FILENAME
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text())
        if set(meta.get("sources", [])) == set(source_names):
            return dict(meta.get("suffixes", {}))
    raise SystemExit(
        f"Table {name!r} already exists and is not a merge of "
        f"{', '.join(source_names)}; pass a different --table-label."
    )


def merge_level(
    ctx: MergeCtx, sources: list[Table], label: str, lift: bool = False
) -> tuple[Table, dict[str, str]]:
    """Merge ``sources`` into one table at the deepest gen; returns it with the
    per-source row-name suffixes.

    Sources at that gen ("deep") contribute their rows. Sources below it
    ("shallow", only with ``lift``) first join the parent level, then re-enter
    here as pass-through copies of their own rows one level down. Whenever the
    parent level holds more than one table it is merged first, recursively (the
    ghost), so every level keeps a single parent.
    """
    gens = {s.gen for s in sources}
    if len(gens) > 1 and not lift:
        listing = ", ".join(f"{s.table_name} (gen {s.gen})" for s in sources)
        raise SystemExit(
            f"All sources must share the same gen. Got: {listing}. "
            "Pass --lift to pad the shallower lineage with pass-through copies."
        )
    gen = max(gens)  # type: ignore[type-var]
    deep = [s for s in sources if s.gen == gen]
    shallow = [s for s in sources if s.gen != gen]

    # The parent level: the deep sources' parents, plus the shallow sources themselves.
    parents = sorted(
        {s.parent_table_name for s in deep} | {s.table_name for s in shallow},
        key=lambda p: p or "",
    )
    ghost: Table | None = None
    parent_suffixes: dict[str, str] = {}
    if len(parents) == 1:
        parent = parents[0]
        target = ctx.registry.derive_new_table(parent, label)
        parent_labels = {
            parent: (ctx.registry.get_table(parent).table_label or "")
            if parent
            else ""
        }
    else:
        parent_tables = [ctx.registry.get_table(p) for p in parents]  # type: ignore[arg-type]
        ghost, parent_suffixes = merge_level(ctx, parent_tables, label, lift)
        target = Table(
            table_name=f"table{gen}_{ghost.table_label}",
            gen=gen,
            table_label=ghost.table_label,
            parent_table_name=ghost.table_name,
        )
        parent_labels = {t.table_name: t.table_label or "" for t in parent_tables}
    target.tool_name = MERGE_TOOL

    source_names = [s.table_name for s in sources]
    existing = _existing_merge(ctx, target.table_name, source_names)
    if existing is not None:
        return ctx.registry.get_table(target.table_name), existing

    frames: list[pd.DataFrame] = []
    suffixes: dict[str, str] = {}
    for source in deep:
        df = ctx.read_frame(source.table_name)
        df[MERGE_SOURCE] = source.table_name
        parent_suffix = parent_suffixes.get(source.parent_table_name or "", "")
        suffix = _join(
            parent_suffix,
            own_label(source, parent_labels[source.parent_table_name]),  # type: ignore
        )
        suffixes[source.table_name] = suffix
        if ghost is not None:
            df[PARENT_TABLE] = ghost.table_name
            if parent_suffix and PARENT_NAME in df.columns:
                df[PARENT_NAME] = df[PARENT_NAME].map(
                    lambda n: n if pd.isna(n) else f"{n}_{parent_suffix}"
                )
        if suffix:
            df.index = pd.Index(
                [f"{n}_{suffix}" for n in df.index], name=df.index.name
            )
        frames.append(df)
    for source in shallow:
        # Pass-through copy: each row's parent is itself one level down (in the
        # ghost when there is one, else in the source table), restamped to this gen.
        df = ctx.read_frame(source.table_name)
        df[MERGE_SOURCE] = source.table_name
        suffix = parent_suffixes.get(source.table_name, "")
        suffixes[source.table_name] = suffix
        names = [f"{n}_{suffix}" if suffix else str(n) for n in df.index]
        df[PARENT_NAME] = names
        df[PARENT_TABLE] = ghost.table_name if ghost else source.table_name
        df[GEN] = gen
        df.index = pd.Index(names, name=df.index.name)
        frames.append(df)

    df = pd.concat(frames)
    dup = df.index[df.index.duplicated()].unique()
    if len(dup):
        preview = ", ".join(map(str, dup[:5])) + (" ..." if len(dup) > 5 else "")
        raise SystemExit(
            f"{len(dup)} row name(s) collide after suffixing: {preview}. "
            "Rename the rows or merge from tables with distinct labels."
        )

    ctx.registry.register_table(target)
    ctx.write_frame(target.table_name, df)

    out_dir = ctx.run_dir / target.table_name / MERGE_TOOL
    out_dir.mkdir(parents=True, exist_ok=True)
    write_run_meta(
        out_dir,
        tool=MERGE_TOOL,
        sources=source_names,
        suffixes=suffixes,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return target, suffixes


def merge_from_args(args: MergeArgs) -> None:
    """Dispatch for ``sapia merge``: pool same-gen tables into a new table."""
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
        ctx = MergeCtx(args.run_dir, read_frame, save_frame, registry)
        merged, _ = merge_level(ctx, sources, args.table_label, args.lift)

    # Sole stdout line: the merged table name, so it can be captured.
    print(merged.table_name)
