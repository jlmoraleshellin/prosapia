"""Read-only, mtime-keyed access to a run's tables for the server.

The cache plugs into ``DataManager`` as its backend, so the registry, lineage
joins and ancestor walks all share one parsed frame per TSV, re-read only when
the file's (mtime, size) changes. Writes are refused.
"""

import math
import threading
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.data_manager import REGISTRY_TABLE, Backend, DataManager
from ..core.naming import MERGE_SOURCE, PARENT_NAME, PARENT_TABLE
from .paths import is_structure

Stamp = tuple[int, int] | None
Columns = list[dict]
Payload = dict


@dataclass
class RunCache:
    run_dir: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    raw: dict[str, tuple[Stamp, pd.DataFrame]] = field(default_factory=dict)
    joined: dict[tuple[str, bool], tuple[tuple, pd.DataFrame, Columns, Payload]] = field(
        default_factory=dict
    )
    stale: set[str] = field(default_factory=set)


def table_path(cache: RunCache, table: str) -> Path:
    return cache.run_dir / f"{table}.tsv"


def stamp(path: Path) -> Stamp:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def empty_frame() -> pd.DataFrame:
    frame = pd.DataFrame()
    frame.index.name = "name"
    return frame


def load_raw(cache: RunCache, table: str) -> pd.DataFrame:
    """The table's frame, re-read when its file changed. A file that fails to parse
    (a collect mid-write) keeps serving the previous frame and marks the table stale."""
    path = table_path(cache, table)
    st = stamp(path)
    with cache.lock:
        hit = cache.raw.get(table)
        if st is None:
            cache.raw.pop(table, None)
            cache.stale.discard(table)
            return empty_frame()
        if hit and hit[0] == st:
            return hit[1]
        try:
            frame = pd.read_csv(path, sep="\t", index_col="name")
        except ValueError:
            if hit:
                cache.stale.add(table)
                return hit[1]
            return empty_frame()
        cache.raw[table] = (st, frame)
        cache.stale.discard(table)
        return frame


def refuse_write(table: str, df: pd.DataFrame) -> None:
    raise RuntimeError("sapia serve is read-only")


def cached_backend(cache: RunCache) -> Backend:
    return partial(load_raw, cache), refuse_write


def open_run(run_dir: Path) -> tuple[RunCache, DataManager]:
    cache = RunCache(run_dir)
    return cache, DataManager(run_dir, build_backend=lambda _: cached_backend(cache))


def table_names(cache: RunCache, dm: DataManager) -> list[str]:
    """Registered tables plus any ``*.tsv`` sitting in the run_dir unregistered."""
    names = [str(n) for n in dm.rm.get_registry().index]
    for p in sorted(cache.run_dir.glob("*.tsv")):
        if not p.stem.startswith("_") and p.stem not in names:
            names.append(p.stem)
    return names


def chain_tables(dm: DataManager, table: str) -> list[str]:
    """The registry, the table, then its ancestors nearest first."""
    chain = [REGISTRY_TABLE, table]
    t = dm.rm.get_table(table)
    while t.parent_table_name and t.parent_table_name not in chain:
        chain.append(t.parent_table_name)
        t = dm.rm.get_table(t.parent_table_name)
    return chain


def load_table(
    cache: RunCache, dm: DataManager, table: str, joined: bool
) -> tuple[pd.DataFrame, Columns, Payload]:
    """The table (lineage-joined or own columns) with ``name`` as a column, its column
    meta and its JSON payload, recomputed when any table in the chain changed."""
    chain = chain_tables(dm, table) if joined else [table]
    stamps = tuple(stamp(table_path(cache, t)) for t in chain)
    key = (table, joined)
    with cache.lock:
        hit = cache.joined.get(key)
    if hit and hit[0] == stamps:
        return hit[1:]
    df = dm.join_lineage(table) if joined else load_raw(cache, table)
    df = coerce_numeric(df.reset_index())
    own = set(load_raw(cache, table).columns) | {"name"}
    ancestors = [(t, set(load_raw(cache, t).columns)) for t in chain[2:]]
    columns = analyze_columns(df, own, ancestors)
    payload = frame_payload(df)
    with cache.lock:
        cache.joined[key] = (stamps, df, columns, payload)
    return df, columns, payload


KEEP_TEXT = {"name", PARENT_NAME, PARENT_TABLE, MERGE_SOURCE}


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Object columns whose every value parses as a number become numeric (a TSV
    re-read after an ``update`` can land as strings)."""
    for col in df.columns:
        s = df[col]
        if col in KEEP_TEXT or is_numeric(s) or pd.api.types.is_bool_dtype(s):
            continue
        n = int(s.notna().sum())
        if n == 0:
            continue
        num = pd.to_numeric(s, errors="coerce")
        if int(num.notna().sum()) == n:
            df[col] = num
    return df


def is_numeric(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def column_source(col: str, own: set[str], ancestors: list[tuple[str, set[str]]]) -> str:
    if col in own:
        return "own"
    for name, cols in ancestors:
        if col in cols or col.startswith(f"{name}__"):
            return name
    return "own"


def analyze_columns(
    df: pd.DataFrame, own: set[str], ancestors: list[tuple[str, set[str]]]
) -> Columns:
    meta = []
    for col in df.columns:
        s = df[col]
        n = int(s.notna().sum())
        entry: dict = {
            "name": str(col),
            "source": column_source(str(col), own, ancestors),
            "is_numeric": is_numeric(s),
            "n_non_null": n,
        }
        if entry["is_numeric"]:
            if n:
                entry["min"] = float(s.min())
                entry["max"] = float(s.max())
        else:
            vals = s.dropna().astype(str)
            entry["n_unique"] = int(vals.nunique())
            entry["is_path"] = bool(n) and bool(vals.head(50).map(is_structure).any())
        meta.append(entry)
    return meta


def json_value(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, np.generic):
        return json_value(v.item())
    return str(v)


def frame_payload(df: pd.DataFrame) -> Payload:
    """The frame as columns of JSON-safe values: far smaller than one dict per row
    when a joined table carries hundreds of columns."""
    return {
        "names": [str(c) for c in df.columns],
        "cols": [[json_value(v) for v in df[c].tolist()] for c in df.columns],
    }


def row_dict(df: pd.DataFrame, i: int) -> dict:
    return {str(c): json_value(v) for c, v in zip(df.columns, df.iloc[i].tolist())}
