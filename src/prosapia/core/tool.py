from dataclasses import dataclass, replace
from typing import Callable, Literal, TypedDict, Unpack

from .base_collect import CollectArgs, CollectFn
from .base_sbatch import CommonArgs, BuildManifestFn

Action = Literal["create", "update"]


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    action: Action
    run_description: str = ""
    collect_description: str = ""

    @property
    def creates_db(self) -> bool:
        """True when the tool reserves a new db (a child *or* a root)."""
        return self.action == "create"


class ToolOverrides(TypedDict, total=False):
    name: str
    action: Action
    run_description: str
    collect_description: str
    default_sbatch: str
    default_input_column: str
    build_manifest_fn: BuildManifestFn
    collect_fn: CollectFn
    add_run_args_fn: Callable | None
    run_args_type: type
    add_collect_args_fn: Callable | None
    collect_args_type: type


@dataclass(frozen=True)
class Tool:
    # Metadata
    name: str
    action: Action
    run_description: str
    collect_description: str
    default_sbatch: str
    default_input_column: str
    build_manifest_fn: BuildManifestFn
    collect_fn: CollectFn
    add_run_args_fn: Callable | None = None
    run_args_type: type = CommonArgs
    add_collect_args_fn: Callable | None = None
    collect_args_type: type = CollectArgs

    @property
    def metadata(self) -> ToolMetadata:
        """Return this tool's metadata"""
        return ToolMetadata(
            self.name,
            self.action,
            self.run_description,
            self.collect_description,
        )

    def with_overrides(self, **overrides: Unpack[ToolOverrides]) -> "Tool":
        return replace(self, **overrides)
