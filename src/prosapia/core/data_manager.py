from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .naming import GEN, PARENT_TABLE, PARENT_NAME, ROOT_PARENT

# The table catalog ("registry") is just another frame -- a TSV read/written
# through the same DataManager backend as every data table. Its index ("name") holds
# table names; columns describe the table graph.
REGISTRY_TABLE = "_registry"


def _norm(value) -> str:
    """Normalize a registry cell for identity comparison.

    Treats NA/None/blank as ``""`` and collapses integral floats to their int
    form, so a ``gen`` read back as ``1.0`` matches a freshly computed ``1``
    (pandas upcasts int columns to float when a row is appended via ``.loc``).
    """
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass
class Table:
    """Handle to a table: its name plus the lineage metadata from the registry."""

    table_name: str
    gen: int | None = None
    table_label: str | None = None
    parent_table_name: str | None = None
    tool_name: str | None = None


# Data backend can be a single function with two methods:
# - read
# - write

# Both are constant and only knows about pandas as it will always be the main df manager.
Frames = dict[str, pd.DataFrame]
BackendRead = Callable[[str], pd.DataFrame]
BackendWrite = Callable[[str, pd.DataFrame], None]
Backend = tuple[BackendRead, BackendWrite]


def build_tsv_backend(run_dir: Path) -> tuple[BackendRead, BackendWrite]:

    def read_frame_from_tsv(table_name: str) -> pd.DataFrame:
        for table_path in run_dir.glob("*.tsv"):
            if table_path.stem == table_name:
                frame = pd.read_csv(table_path, sep="\t", index_col="name")
                return frame
        else:
            print(f"Table {table_name} is new. Initializing new table.")
            frame = pd.DataFrame()
            frame.index.name = "name"
            return frame

    def write_frame_to_tsv(table_name: str, df: pd.DataFrame) -> None:
        df.to_csv(run_dir / f"{table_name}.tsv", sep="\t")

    return read_frame_from_tsv, write_frame_to_tsv


class RegistryManager:
    """The table catalog (the ``_registry`` table): table-level lineage, read fresh per op."""

    def __init__(self, data_manager: "DataManager"):
        self.dm = data_manager

    def _read(self) -> pd.DataFrame:
        """Read the registry frame fresh (empty frame if it doesn't exist yet)."""
        return self.dm.read_frame(REGISTRY_TABLE)

    def derive_new_table(self, parent_table: str | None, table_label: str = "") -> Table:
        """Derive a new table handle (root if ``parent_table`` is None, else a child). Pure; does not register."""
        reg = self._read()
        if parent_table:
            if parent_table not in reg.index:
                raise KeyError(
                    f"Parent table {parent_table!r} not in registry. Create it first."
                )
            gen = int(reg.at[parent_table, GEN]) + 1  # type: ignore
            raw = reg.at[parent_table, "table_label"]
            parent_label = "" if pd.isna(raw) else str(raw)
            if table_label and parent_label:
                label = f"{parent_label}_{table_label}"
            else:
                label = table_label or parent_label
        else:
            gen = 0
            label = table_label

        name = f"table{gen}_{label}" if label else f"table{gen}"
        return Table(
            table_name=name,
            gen=gen,
            table_label=label,
            parent_table_name=parent_table,
        )

    def register_table(self, table: Table) -> None:
        """Record a new table in the registry; idempotent on identical lineage, raises on a conflicting one."""
        reg = self._read()
        parent_sentinel = (
            table.parent_table_name if table.parent_table_name else ROOT_PARENT
        )
        if table.table_name in reg.index:
            existing = reg.loc[table.table_name]
            want_identity = {
                PARENT_TABLE: parent_sentinel,
                GEN: table.gen,
                "table_label": table.table_label,
            }
            mismatches = {
                k: (existing.get(k), v)
                for k, v in want_identity.items()
                if _norm(existing.get(k)) != _norm(v)
            }
            if mismatches:
                raise ValueError(
                    f"Table {table.table_name!r} already registered with different "
                    f"lineage: {mismatches}. Pass a distinct table_label to fork."
                )
            return  # same table already present -> no-op, preserve created_at
        reg = self.dm.update(
            reg,
            table.table_name,
            {
                GEN: int(table.gen),  # type: ignore
                "table_label": table.table_label or pd.NA,
                PARENT_TABLE: parent_sentinel,
                "tool": table.tool_name,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        self.dm.write_frame(REGISTRY_TABLE, reg)

    def get_table(self, table_name: str) -> Table:
        """Return the ``Table`` handle for ``table_name`` (bare handle with ``None`` metadata if unregistered)."""
        reg = self._read()
        if table_name not in reg.index:
            return Table(table_name=table_name)
        row = reg.loc[table_name]
        parent = row[PARENT_TABLE]
        raw_tool = row["tool"] if "tool" in reg.columns else None
        return Table(
            table_name=table_name,
            gen=int(row[GEN]),  # type: ignore
            table_label=_norm(row["table_label"]),
            parent_table_name=None if parent == ROOT_PARENT else str(parent),  # type: ignore
            tool_name=str(raw_tool) if pd.notna(raw_tool) else None,  # type: ignore
        )

    def get_registry(self) -> pd.DataFrame:
        """The table registry as a DataFrame (index = table name)."""
        return self._read()


class DataManager:
    """Facade over a run_dir's data, usable as a context manager.

    Unpacks as ``(dm, (read_frame, write_frame), rm)``; ``__exit__`` is scope-only.
    """

    def __init__(
        self,
        run_dir: Path,
        build_backend: Callable[..., Backend] = build_tsv_backend,
    ):
        self.read_frame, self.write_frame = build_backend(run_dir)
        self.rm = RegistryManager(self)

    def __enter__(
        self,
    ) -> tuple["DataManager", Backend, RegistryManager]:
        return self, (self.read_frame, self.write_frame), self.rm

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, df: pd.DataFrame, iname: str, data: dict) -> pd.DataFrame:
        """Set ``data`` on row ``iname`` (adding columns as needed); guards name reuse for a different sequence."""
        if "sequence" in data and iname in df.index and "sequence" in df.columns:
            old = df.at[iname, "sequence"]
            new = data["sequence"]
            if pd.notna(old) and pd.notna(new) and old != new:
                raise ValueError(
                    f"Sequence collision for {iname!r} in dataframe: the existing "
                    f"sequence differs from the new one. Names must be unique per "
                    f"sequence."
                )

        for k, v in data.items():
            if k not in df.columns:
                df[k] = pd.NA
            try:
                df.loc[iname, k] = v
            except (TypeError, ValueError):
                # Existing column dtype can't hold v (e.g. a str into an
                # all-NaN float64 column read back from TSV); widen to object.
                df[k] = df[k].astype(object)
                df.loc[iname, k] = v
        return df

    def trace_lineage(
        self, table_name: str, name: str, include_self: bool = False
    ) -> list[tuple[str, str]]:
        """Walk ``parent_table``/``parent_name`` from a row to the root, returning ``(table, name)`` pairs."""
        chain: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        cur_table, cur_name = table_name, name
        if include_self:
            chain.append((cur_table, cur_name))
        while True:
            df = self.read_frame(cur_table)
            if cur_name not in df.index:
                break
            row = df.loc[cur_name]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            parent_table = row.get(PARENT_TABLE) if PARENT_TABLE in row.index else None
            parent_name = row.get(PARENT_NAME) if PARENT_NAME in row.index else None
            if (
                parent_table is None
                or parent_name is None
                or pd.isna(parent_table)
                or pd.isna(parent_name)
            ):
                break
            key = (str(parent_table), str(parent_name))
            if key in seen:  # cycle guard
                break
            seen.add(key)
            chain.append(key)
            cur_table, cur_name = key
        return chain

    def join_lineage(self, table_name: str) -> pd.DataFrame:
        """Return ``table_name``'s frame left-joined with every ancestor table's columns.

        Walks the table-level parent chain from the registry (nearest ancestor
        first). At each hop it joins on the working frame's current
        ``parent_name`` -> the ancestor's index, then carries the ancestor's own
        ``parent_name`` forward as the next join key. Ancestor columns are merged
        under their plain names; a name already present in a closer frame is
        suffixed with the ancestor table name (e.g. ``table0_grow_hairpin__parent_name``).
        Ancestor ``*_status`` columns are dropped; ``*_path`` columns are kept so
        ancestor structures stay viewable. A root table (no parent) is returned as-is.
        """
        frame = self.read_frame(table_name)
        if frame.empty or PARENT_NAME not in frame.columns:
            return frame

        joined = frame.copy()
        current_key = frame[PARENT_NAME]
        table = self.rm.get_table(table_name)
        seen: set[str] = {table_name}

        while table.parent_table_name and table.parent_table_name not in seen:
            seen.add(table.parent_table_name)
            anc = self.read_frame(table.parent_table_name)
            if anc.empty:
                break
            aligned = anc.reindex(current_key.values)
            for col in anc.columns:
                if col.endswith("_status"):
                    continue
                out_col = (
                    f"{table.parent_table_name}__{col}" if col in joined.columns else col
                )
                joined[out_col] = aligned[col].to_numpy()
            # Carry the ancestor's parent_name forward as the next join key.
            if PARENT_NAME in anc.columns:
                current_key = pd.Series(
                    aligned[PARENT_NAME].to_numpy(), index=joined.index
                )
            else:
                break
            table = self.rm.get_table(table.parent_table_name)

        return joined

    def lookup(self, df: pd.DataFrame, name: str, column: str, default=pd.NA):
        """Read ``column`` for ``name``, resolving inherited values up the lineage (df-first)."""
        cur_df, cur_name = df, name
        seen: set[tuple[str, str]] = set()
        while True:
            if cur_name in cur_df.index and column in cur_df.columns:
                val = cur_df.at[cur_name, column]
                if isinstance(val, pd.Series):
                    val = val.iloc[0]
                if pd.notna(val):
                    return val
            if cur_name not in cur_df.index:
                return default
            row = cur_df.loc[cur_name]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            parent_table = row.get(PARENT_TABLE) if PARENT_TABLE in row.index else None
            parent_name = row.get(PARENT_NAME) if PARENT_NAME in row.index else None
            if (
                parent_table is None
                or parent_name is None
                or pd.isna(parent_table)
                or pd.isna(parent_name)
            ):
                return default
            key = (str(parent_table), str(parent_name))
            if key in seen:  # cycle guard
                return default
            seen.add(key)
            cur_df, cur_name = self.read_frame(str(parent_table)), str(parent_name)


# Type alias for a lineage lookup function (row name + column -> value)
# walking parent_table/parent_name. No write access to the DataManager is exposed.
LookupFn = Callable[[str, str], Any]


# FILTERING FUNCTIONS
def filter_ready(df: pd.DataFrame, input_column: str) -> pd.DataFrame:
    """Rows whose ``input_column`` is present (non-null, non-empty) -- the inputs a
    run/collect should act on.

    Defensive: an empty frame or a missing ``input_column`` yields ``df`` unchanged,
    so root tools (empty source table) and tools that key off a different column never
    crash on this shared filter.
    """
    if df.empty or input_column not in df.columns:
        return df
    col = df[input_column]
    return df[col.notna() & (col != "")]
