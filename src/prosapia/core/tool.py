from dataclasses import dataclass, replace
from typing import Callable, Literal, TypedDict, Unpack

from .base_collect import CollectArgs, CollectFn
from .base_sbatch import CommonArgs, BuildManifestFn

Action = Literal["create", "update"]


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    action: Action
    description: str = ""
    default_input_column: str = ""

    @property
    def creates_db(self) -> bool:
        """True when the tool reserves a new db (a child *or* a root)."""
        return self.action == "create"


class ToolOverrides(TypedDict, total=False):
    name: str
    action: Action
    description: str
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
    default_sbatch: str
    default_input_column: str
    build_manifest_fn: BuildManifestFn
    collect_fn: CollectFn
    description: str = ""
    add_run_args_fn: Callable | None = None
    run_args_type: type = CommonArgs
    add_collect_args_fn: Callable | None = None
    collect_args_type: type = CollectArgs

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
