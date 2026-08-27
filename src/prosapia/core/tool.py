from dataclasses import dataclass
from typing import Callable, Literal

from .base_collect import CollectArgs
from .base_sbatch import CommonArgs

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


@dataclass(frozen=True)
class Tool:
    # Metadata
    name: str
    action: Action
    run_description: str
    collect_description: str
    default_sbatch: str
    default_input_column: str
    build_fn: Callable
    collect_fn: Callable
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
