"""Naming conventions for tool output dirs, columns, and lineage.

A tool writes to a nested dir ``run_dir/<source_table>/<leaf>/`` and to the matching
``<leaf>_path`` / ``<leaf>_status`` columns; the table already scopes the columns, so
the leaf stays short. Cross-table provenance comes from the lineage columns below.
"""

from argparse import (
    Namespace,  # TODO fix circular import with base_collect, this should be CollectArgs
)
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .data_manager import Table
    from .tool import ToolMetadata

# Row-level lineage columns.
PARENT_NAME = "parent_name"  # the parent row's name
PARENT_TABLE = "parent_table"  # the table the parent row lives in
GEN = "gen"  # generation depth (root = 0); per-row for concat

# parent_table sentinel for a root table (no parent)
ROOT_PARENT = "root"

# Per-out_dir sidecar: records the run parameters
# that aren't recoverable from the table itself
RUN_META_FILENAME = ".meta.json"


def build_tool_leaf(tool: str, dir_label: str = "") -> str:
    """Leaf name for a tool's output dir and table column prefix (``tool[_dir_label]``)."""
    return f"{tool}_{dir_label}" if dir_label else tool


def status_column(leaf: str) -> str:
    """The ``<leaf>_status`` column a tool writes/reads for a design's run state."""
    return f"{leaf}_status"


def path_column(leaf: str) -> str:
    """The ``<leaf>_path`` column a tool writes/reads for a design's output path."""
    return f"{leaf}_path"


def resolve_dir_name(
    args: Namespace,
    table: "Table",
    tool_metadata: "ToolMetadata",
    must_exist: bool = True,
) -> Path:
    """Resolve a tool's nested output dir ``run_dir/<table>/<leaf>`` (leaf keyed by the running tool).

    ``must_exist`` raises ``FileNotFoundError`` when the dir is absent.
    """
    src_dir = (
        args.run_dir
        / table.table_name
        / build_tool_leaf(tool_metadata.name, args.dir_label)
    )
    if must_exist and not src_dir.is_dir():
        raise FileNotFoundError(f"Output dir not found: {src_dir}")
    return src_dir
