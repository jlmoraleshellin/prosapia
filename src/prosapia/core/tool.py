from dataclasses import dataclass, replace
from typing import Callable, Literal, TypedDict, Unpack

from .base_collect import CollectArgs, CollectorFactory, collect_from_args
from .base_run import BuildManifestFn, CommonArgs, run_from_args
from .data_manager import DataManager
from .naming import SUBMISSIONS_DIRNAME, build_tool_leaf

Action = Literal["create", "update"]


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    action: Action
    description: str = ""
    default_input_column: str = ""

    @property
    def creates_table(self) -> bool:
        """True when the tool reserves a new table (a child *or* a root)."""
        return self.action == "create"


class ToolOverrides(TypedDict, total=False):
    name: str
    action: Action
    description: str
    default_script: str
    default_input_column: str
    build_manifest_fn: BuildManifestFn
    collect_fn: CollectorFactory
    add_run_args_fn: Callable | None
    add_collect_args_fn: Callable | None


@dataclass(frozen=True)
class Tool:
    # Metadata
    name: str
    action: Action
    default_script: str
    default_input_column: str
    build_manifest_fn: BuildManifestFn
    collect_fn: CollectorFactory
    description: str = ""
    add_run_args_fn: Callable | None = None
    add_collect_args_fn: Callable | None = None

    @property
    def metadata(self) -> ToolMetadata:
        """Return this tool's metadata"""
        return ToolMetadata(
            name=self.name,
            action=self.action,
            description=self.description,
            default_input_column=self.default_input_column,
        )

    def with_overrides(self, **overrides: Unpack[ToolOverrides]) -> "Tool":
        return replace(self, **overrides)


# THE TWO VERBS, at tool level.
def collect_tool(tool: Tool, args: CollectArgs) -> None:
    """``sapia collect <tool>``: fold the tool's on-disk output into its table."""
    collect_from_args(tool.metadata, tool.collect_fn, args)


def run_tool(tool: Tool, args: CommonArgs) -> None:
    """``sapia run <tool>``: collect what earlier submissions produced, then submit
    what is still pending.

    The collect is the resume cache: it writes each design's status into the table,
    and ``run`` then skips the ``OK`` ones. It happens only on a resubmit (the leaf
    already has submission dirs) and never for a root run (no table to read). A
    collect failure aborts the submit: a table that cannot be brought up to date
    would resubmit everything.
    """
    if args.table is not None:
        # Collect takes the table the tool writes to: the child for a create tool.
        if tool.metadata.creates_table:
            with DataManager(args.run_dir) as (_, _, registry):
                out_table = registry.derive_new_table(
                    args.table, getattr(args, "table_label", "")
                ).table_name
        else:
            out_table = args.table
        leaf_dir = args.run_dir / out_table / build_tool_leaf(tool.name, args.dir_label)
        if (leaf_dir / SUBMISSIONS_DIRNAME).is_dir():
            collect_args = CollectArgs(**vars(args))
            collect_args.table = out_table
            collect_args.force = False  # run's --force resubmits; it never re-reads
            collect_tool(tool, collect_args)
    run_from_args(tool.metadata, tool.build_manifest_fn, args)
