from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from .naming import GEN, PARENT_DB, PARENT_NAME, ROOT_PARENT

# The database catalog ("registry") is just another frame -- a TSV read/written
# through the same DataManager backend as every data db. Its index ("name") holds
# database names; columns describe the db graph.
REGISTRY_DB = "_registry"


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
class Database:
    """Handle to a database: its name plus the lineage metadata from the registry."""

    db_name: str
    gen: int | None = None
    db_label: str | None = None
    parent_db_name: str | None = None
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

    def read_frame_from_tsv(db_name: str) -> pd.DataFrame:
        for db_path in run_dir.glob("*.tsv"):
            if db_path.stem == db_name:
                frame = pd.read_csv(db_path, sep="\t", index_col="name")
                return frame
        else:
            print(f"Database {db_name} is new. Initializing new database.")
            frame = pd.DataFrame()
            frame.index.name = "name"
            return frame

    def write_frame_to_tsv(db_name: str, df: pd.DataFrame) -> None:
        df.to_csv(run_dir / f"{db_name}.tsv", sep="\t")

    return read_frame_from_tsv, write_frame_to_tsv


class RegistryManager:
    """The database catalog (the ``_registry`` table): db-level lineage, read fresh per op."""

    def __init__(self, data_manager: "DataManager"):
        self.dm = data_manager

    def _read(self) -> pd.DataFrame:
        """Read the registry frame fresh (empty frame if it doesn't exist yet)."""
        return self.dm.read_frame(REGISTRY_DB)

    def derive_new_db(self, parent_db: str | None, db_label: str = "") -> Database:
        """Derive a new db handle (root if ``parent_db`` is None, else a child). Pure; does not register."""
        reg = self._read()
        if parent_db:
            if parent_db not in reg.index:
                raise KeyError(
                    f"Parent database {parent_db!r} not in registry. Create it first."
                )
            gen = int(reg.at[parent_db, GEN]) + 1  # type: ignore
            raw = reg.at[parent_db, "db_label"]
            parent_label = "" if pd.isna(raw) else str(raw)
            if db_label and parent_label:
                label = f"{parent_label}_{db_label}"
            else:
                label = db_label or parent_label
        else:
            gen = 0
            label = db_label

        name = f"db{gen}_{label}" if label else f"db{gen}"
        return Database(
            db_name=name,
            gen=gen,
            db_label=label,
            parent_db_name=parent_db,
        )

    def register_database(self, database: Database) -> None:
        """Record a new db in the registry; idempotent on identical lineage, raises on a conflicting one."""
        reg = self._read()
        parent_sentinel = (
            database.parent_db_name if database.parent_db_name else ROOT_PARENT
        )
        if database.db_name in reg.index:
            existing = reg.loc[database.db_name]
            want_identity = {
                PARENT_DB: parent_sentinel,
                GEN: database.gen,
                "db_label": database.db_label,
            }
            mismatches = {
                k: (existing.get(k), v)
                for k, v in want_identity.items()
                if _norm(existing.get(k)) != _norm(v)
            }
            if mismatches:
                raise ValueError(
                    f"Database {database.db_name!r} already registered with different "
                    f"lineage: {mismatches}. Pass a distinct db_label to fork."
                )
            return  # same db already present -> no-op, preserve created_at
        reg = self.dm.update(
            reg,
            database.db_name,
            {
                GEN: int(database.gen),  # type: ignore
                "db_label": database.db_label or pd.NA,
                PARENT_DB: parent_sentinel,
                "tool": database.tool_name,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        self.dm.write_frame(REGISTRY_DB, reg)

    def get_database(self, db_name: str) -> Database:
        """Return the ``Database`` handle for ``db_name`` (bare handle with ``None`` metadata if unregistered)."""
        reg = self._read()
        if db_name not in reg.index:
            return Database(db_name=db_name)
        row = reg.loc[db_name]
        parent = row[PARENT_DB]
        raw_tool = row["tool"] if "tool" in reg.columns else None
        return Database(
            db_name=db_name,
            gen=int(row[GEN]),  # type: ignore
            db_label=_norm(row["db_label"]),
            parent_db_name=None if parent == ROOT_PARENT else str(parent),  # type: ignore
            tool_name=str(raw_tool) if pd.notna(raw_tool) else None,  # type: ignore
        )

    def get_registry(self) -> pd.DataFrame:
        """The database registry as a DataFrame (index = database name)."""
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
        self, db_name: str, name: str, include_self: bool = False
    ) -> list[tuple[str, str]]:
        """Walk ``parent_db``/``parent_name`` from a row to the root, returning ``(db, name)`` pairs."""
        chain: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        cur_db, cur_name = db_name, name
        if include_self:
            chain.append((cur_db, cur_name))
        while True:
            df = self.read_frame(cur_db)
            if cur_name not in df.index:
                break
            row = df.loc[cur_name]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            parent_db = row.get(PARENT_DB) if PARENT_DB in row.index else None
            parent_name = row.get(PARENT_NAME) if PARENT_NAME in row.index else None
            if (
                parent_db is None
                or parent_name is None
                or pd.isna(parent_db)
                or pd.isna(parent_name)
            ):
                break
            key = (str(parent_db), str(parent_name))
            if key in seen:  # cycle guard
                break
            seen.add(key)
            chain.append(key)
            cur_db, cur_name = key
        return chain

    def join_lineage(self, db_name: str) -> pd.DataFrame:
        """Return ``db_name``'s frame left-joined with every ancestor db's columns.

        Walks the db-level parent chain from the registry (nearest ancestor
        first). At each hop it joins on the working frame's current
        ``parent_name`` -> the ancestor's index, then carries the ancestor's own
        ``parent_name`` forward as the next join key. Ancestor columns are merged
        under their plain names; a name already present in a closer frame is
        suffixed with the ancestor db name (e.g. ``db0_grow_hairpin__parent_name``).
        Ancestor ``*_status`` columns are dropped; ``*_path`` columns are kept so
        ancestor structures stay viewable. A root db (no parent) is returned as-is.
        """
        frame = self.read_frame(db_name)
        if frame.empty or PARENT_NAME not in frame.columns:
            return frame

        joined = frame.copy()
        current_key = frame[PARENT_NAME]
        db = self.rm.get_database(db_name)
        seen: set[str] = {db_name}

        while db.parent_db_name and db.parent_db_name not in seen:
            seen.add(db.parent_db_name)
            anc = self.read_frame(db.parent_db_name)
            if anc.empty:
                break
            aligned = anc.reindex(current_key.values)
            for col in anc.columns:
                if col.endswith("_status"):
                    continue
                out_col = (
                    f"{db.parent_db_name}__{col}" if col in joined.columns else col
                )
                joined[out_col] = aligned[col].to_numpy()
            # Carry the ancestor's parent_name forward as the next join key.
            if PARENT_NAME in anc.columns:
                current_key = pd.Series(
                    aligned[PARENT_NAME].to_numpy(), index=joined.index
                )
            else:
                break
            db = self.rm.get_database(db.parent_db_name)

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
            parent_db = row.get(PARENT_DB) if PARENT_DB in row.index else None
            parent_name = row.get(PARENT_NAME) if PARENT_NAME in row.index else None
            if (
                parent_db is None
                or parent_name is None
                or pd.isna(parent_db)
                or pd.isna(parent_name)
            ):
                return default
            key = (str(parent_db), str(parent_name))
            if key in seen:  # cycle guard
                return default
            seen.add(key)
            cur_df, cur_name = self.read_frame(str(parent_db)), str(parent_name)
