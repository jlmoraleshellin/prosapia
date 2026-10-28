"""The workflow tree of a run_dir: tables from the registry, each with the tool
runs found under ``run_dir/<table>/<leaf>/`` and a status inferred from what is on
disk, since the registry records lineage only."""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from ..core.data_manager import DataManager
from ..core.naming import GEN, PARENT_TABLE, ROOT_PARENT, RUN_META_FILENAME, status_column
from .tables import RunCache, empty_frame, load_raw, stamp

MERGE_TOOL = "merge"


@dataclass
class Leaf:
    name: str
    tool: str
    dir_label: str
    kind: str  # create | update | merge
    status: str  # reserved | submitted | collected
    meta: dict | None
    tasks: dict
    rows: dict | None


@dataclass
class TableNode:
    name: str
    gen: int | None = None
    label: str = ""
    parent: str | None = None
    tool: str | None = None
    created_at: str | None = None
    registered: bool = True
    collected: bool = False
    n_rows: int | None = None
    mtime: float | None = None
    sources: list[str] = field(default_factory=list)
    leaves: list[Leaf] = field(default_factory=list)


def _text(v) -> str | None:
    return None if v is None or pd.isna(v) else str(v)


def table_nodes(cache: RunCache, dm: DataManager) -> list[TableNode]:
    nodes: dict[str, TableNode] = {}
    reg = dm.rm.get_registry()
    for name, row in reg.iterrows():
        gen = row.get(GEN)
        parent = _text(row.get(PARENT_TABLE))
        nodes[str(name)] = TableNode(
            name=str(name),
            gen=None if gen is None or pd.isna(gen) else int(float(gen)),
            label=_text(row.get("table_label")) or "",
            parent=None if parent == ROOT_PARENT else parent,
            tool=_text(row.get("tool")),
            created_at=_text(row.get("created_at")),
        )
    for p in sorted(cache.run_dir.glob("*.tsv")):
        if not p.stem.startswith("_") and p.stem not in nodes:
            nodes[p.stem] = TableNode(name=p.stem, registered=False)
    for node in nodes.values():
        st = stamp(cache.run_dir / f"{node.name}.tsv")
        if st is not None:
            node.collected = True
            node.mtime = st[0] / 1e9
            node.n_rows = len(load_raw(cache, node.name))
    return list(nodes.values())


def read_meta(leaf_dir: Path) -> dict | None:
    path = leaf_dir / RUN_META_FILENAME
    try:
        meta = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def log_dirs(leaf_dir: Path) -> list[Path]:
    return sorted(p for p in leaf_dir.glob("*_logs") if p.is_dir())


def exit_code(path: Path) -> int:
    try:
        return int(path.read_text().strip() or 255)
    except (OSError, ValueError):
        return 255


def scan_logs(leaf_dir: Path) -> dict:
    """Task counts from the executor logs: one task per ``.out``; pass/fail from
    ``.exit`` files (SLURM writes none, so its tasks stay pending here)."""
    n = ok = failed = 0
    executor = None
    for log_dir in log_dirs(leaf_dir):
        outs = 0
        exits: list[int] = []
        for entry in os.scandir(log_dir):
            if entry.name.endswith(".out"):
                outs += 1
            elif entry.name.endswith(".exit"):
                exits.append(exit_code(Path(entry.path)))
            elif entry.name.endswith("_modal.json"):
                executor = "modal"
        n += outs
        ok += sum(1 for c in exits if c == 0)
        failed += sum(1 for c in exits if c != 0)
        if executor is None and outs:
            executor = "local" if exits else "slurm"
    return {"n": n, "ok": ok, "failed": failed, "pending": n - ok - failed, "executor": executor}


def list_tasks(run_dir: Path, leaf_dir: Path) -> list[dict]:
    tasks = []
    for log_dir in log_dirs(leaf_dir):
        for out in sorted(log_dir.glob("*.out")):
            err = out.with_suffix(".err")
            exit_path = out.with_suffix(".exit")
            tasks.append(
                {
                    "id": out.stem,
                    "exit": exit_code(exit_path) if exit_path.is_file() else None,
                    "out": str(out.relative_to(run_dir)),
                    "err": str(err.relative_to(run_dir)) if err.is_file() else None,
                }
            )
    return tasks


def scan_leaves(run_dir: Path, node: TableNode, frame: pd.DataFrame) -> list[Leaf]:
    table_dir = run_dir / node.name
    if not table_dir.is_dir():
        return []
    leaves = []
    for d in sorted(table_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        meta = read_meta(d)
        if meta is None and not log_dirs(d):
            continue
        meta = meta or {}
        tool = str(meta.get("tool") or d.name)
        if tool == MERGE_TOOL:
            kind = "merge"
        elif tool == node.tool:
            kind = "create"
        else:
            kind = "update"
        tasks = scan_logs(d)
        status_col = status_column(d.name)
        rows = None
        if status_col in frame.columns:
            s = frame[status_col]
            ok = int((s == "OK").sum())
            rows = {"ok": ok, "other": int(s.notna().sum()) - ok}
        if rows is not None or kind == "merge" or (kind == "create" and node.collected):
            status = "collected"
        elif tasks["n"]:
            status = "submitted"
        else:
            status = "reserved"
        leaves.append(
            Leaf(
                name=d.name,
                tool=tool,
                dir_label=str(meta.get("dir_label") or ""),
                kind=kind,
                status=status,
                meta=meta or None,
                tasks=tasks,
                rows=rows,
            )
        )
    return leaves


def build_tree(cache: RunCache, dm: DataManager) -> dict:
    nodes = table_nodes(cache, dm)
    names = {n.name for n in nodes}
    edges = []
    for node in nodes:
        frame = load_raw(cache, node.name) if node.collected else empty_frame()
        node.leaves = scan_leaves(cache.run_dir, node, frame)
        for leaf in node.leaves:
            if leaf.kind == "merge":
                node.sources = [s for s in (leaf.meta or {}).get("sources", []) if s in names]
        if node.parent in names and not node.sources:
            edges.append({"from": node.parent, "to": node.name, "kind": "parent"})
        for src in node.sources:
            edges.append({"from": src, "to": node.name, "kind": "merge"})
    nodes.sort(key=lambda n: (n.gen if n.gen is not None else 999, n.name))
    return {
        "run_dir": str(cache.run_dir),
        "name": cache.run_dir.name,
        "tables": [asdict(n) for n in nodes],
        "edges": edges,
    }
