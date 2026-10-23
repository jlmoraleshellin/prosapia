# PYTHON_ARGCOMPLETE_OK
"""Generic task submission (scheduler chosen by ``--executor``, see ``core.executors``).

Every batch-submission script delegates here, supplying a ``build_manifest_fn``
(filters the table, returns one manifest row per array task) and optionally an
``add_extra_args_fn`` for extra CLI flags. An optional ``--filter`` module's
``apply_filter(df) -> df`` runs before the manifest is built.
"""

from __future__ import annotations

import importlib.util
import json
import os
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Generic, Sequence, TypeVar

import pandas as pd
from dotenv import load_dotenv
from pandas import DataFrame

from .base_parser import base_parser
from .executors import EXECUTORS, SubmitCtx, get_executor
from .data_manager import DataManager, LookupFn, clean_ready
from .naming import (
    PARENT_NAME,
    RUN_META_FILENAME,
    build_tool_leaf,
    resolve_dir_name,
    status_column,
)

if TYPE_CHECKING:
    from .tool import ToolMetadata

load_dotenv()


## ARGPARSER
class CommonArgs(Namespace):
    run_dir: Path
    table: str | None
    script: Path
    executor: str
    modal_gpu: str | None
    input_column: str
    dir_label: str
    table_label: str
    filter: Path | None
    where: list[str] | None
    max_concurrent: int
    partitions: str | None
    account: str | None
    max_gpu_fraction: float
    gpus_per_task: int
    cpus_per_task: int | None
    time: str | None
    mem: str | None
    force: bool


def _add_submit_args(
    parser: ArgumentParser,
    default_script: str,
    default_input_column: str,
) -> None:
    """Add the submission flags shared by every run parser (standalone or ``sapia``)."""
    parser.add_argument(
        "-s",
        "--script",
        type=Path,
        default=default_script,
        help=f"Path to the per-task script. Defaults to '{default_script}'.",
    )
    parser.add_argument(
        "-e",
        "--executor",
        choices=EXECUTORS,
        default=os.getenv("SAPIA_EXECUTOR", "slurm"),
        help="Who runs the tasks: a scheduler (slurm, modal) or this machine "
        "(local). Defaults to $SAPIA_EXECUTOR, else 'slurm'.",
    )
    parser.add_argument(
        "--modal-gpu",
        type=str,
        default=None,
        help="Modal GPU type (e.g. 'A100', 'H100'). Only used with --executor modal; "
        "overrides RESOURCES['gpu'] in the tool's modal_image.py.",
    )
    parser.add_argument(
        "-i",
        "--input-column",
        type=str,
        default=default_input_column,
        help=f"Input column from table. \
        Defaults to '{default_input_column}'",
    )
    parser.add_argument(
        "-l",
        "--dir-label",
        type=str,
        default="",
        help="Suffix for the tool output dir, for same-tool variants "
        "(e.g. different seeds). Default is empty.",
    )
    parser.add_argument(
        "-f",
        "--filter",
        type=Path,
        default=None,
        help="Path to a Python module defining an apply_filter(df) -> df function, "
        "applied to the DataFrame before the manifest is built.",
    )
    parser.add_argument(
        "-w",
        "--where",
        action="append",
        default=None,
        metavar="COL=VALUE",
        help="Keep only rows whose COL equals VALUE (string compare). Repeatable; "
        "applied after --filter. E.g. -w merge_source=table1_a for a per-fork run "
        "on a merged table.",
    )
    parser.add_argument(
        "-C",
        "--max-concurrent",
        type=int,
        default=40,
        help="Max concurrent tasks (SLURM array throttle / Modal max containers / "
        "local slots). Defaults to 40.",
    )
    parser.add_argument(
        "-a",
        "--account",
        type=str,
        default=None,
        help="SLURM account. Default is unset",
    )
    parser.add_argument(
        "-p",
        "--partitions",
        type=str,
        default=None,
        help="Comma-separated partitions with optional GPU counts "
        "(e.g. 'ampere_gpu:40,hopper_gpu:80'). When set, submits one "
        "array per partition, each capped at --max-gpu-fraction of its GPUs. "
        "GPU counts are auto-detected via sinfo if omitted.",
    )
    parser.add_argument(
        "--max-gpu-fraction",
        type=float,
        default=0.5,
        help="Fraction of each partition's GPUs to use as the concurrency cap. "
        "Only used with --partitions. Defaults to 0.5.",
    )
    parser.add_argument(
        "-g",
        "--gpus-per-task",
        type=int,
        default=1,
        help="GPUs requested per task (--gres=gpu:N on SLURM). Can be 0 for CPU-only tasks. "
        "Scripts like run_boltz_batch.py set this automatically from --devices. "
        "Defaults to 1.",
    )
    parser.add_argument(
        "-c",
        "--cpus-per-task",
        type=int,
        default=None,
        help="CPUs per task. Overrides the #SBATCH directive in the tool's .sh "
        "(or RESOURCES in its modal_image.py). Default is unset (use the tool's value).",
    )
    parser.add_argument(
        "-T",
        "--time",
        type=str,
        default=None,
        help="Wall-time limit per task (e.g. '04:00:00'). Overrides the #SBATCH "
        "directive in the tool's .sh (or its modal_image.py). Default is unset.",
    )
    parser.add_argument(
        "--mem",
        type=str,
        default=None,
        help="Memory per task (e.g. '32G'). Overrides the #SBATCH directive in "
        "the tool's .sh (or its modal_image.py). Default is unset.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-submit designs this tool already completed (skips the resume "
        "filter that drops rows whose <leaf>_status is already 'OK').",
    )


def build_run_parser(
    metadata: "ToolMetadata",
    default_script: str,
    default_input_column: str,
    add_extra_args_fn: AddArgsFn | None = None,
) -> ArgumentParser:
    """Build a reusable (``add_help=False``) parent parser holding every run flag for
    a tool: base args + batch flags + ``--table-label`` (create tools) + tool extras.

    Used both by ``submit_sbatch_array`` (as the sole parent of a standalone parser)
    and by the ``sapia`` CLI (as ``parents=[...]`` of each ``run <tool>`` subparser), so
    a single ``argcomplete`` call at the top sees the full argument tree.
    """
    parser = ArgumentParser(
        add_help=False,
        parents=[base_parser(require_table=not metadata.creates_table)],
    )
    _add_submit_args(parser, default_script, default_input_column)
    if metadata.creates_table:
        parser.add_argument(
            "--table-label",
            type=str,
            default="",
            help="Optional label for the child table this run creates "
            "(append rule: table<gen>_<parent_label>_<table_label>). Omit for an "
            "unlabelled child (table<gen>); pass one to disambiguate a fork.",
        )
    if add_extra_args_fn is not None:
        add_extra_args_fn(parser)
    return parser


## FILTERING
FilterFn = Callable[[DataFrame], DataFrame]


def _get_filter_fn_from_module(module_path: Path) -> FilterFn:
    spec = importlib.util.spec_from_file_location("filter_module", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "apply_filter"):
        raise AttributeError(
            f"{module_path} does not define an 'apply_filter' function"
        )
    return module.apply_filter


def apply_where(df: DataFrame, clauses: Sequence[str]) -> DataFrame:
    """Keep rows matching every ``COL=VALUE`` clause (values compared as strings)."""
    for clause in clauses:
        col, sep, value = clause.partition("=")
        if not sep or not col:
            raise ValueError(f"--where expects COL=VALUE, got {clause!r}")
        if col not in df.columns:
            raise KeyError(f"--where column {col!r} not in table columns")
        df = df[df[col].astype(str) == value]
    return df


## MANIFEST BUILDING AND SUBMISSION
ManifestRow = Sequence[str]
AddArgsFn = Callable[[ArgumentParser], None]

ArgsT = TypeVar("ArgsT", bound=CommonArgs)


@dataclass
class ManifestCtx(Generic[ArgsT]):
    """Inputs a manifest builder may read (frames, args, out_dir, lookup).

    ``source_df`` is the table the run iterates, after ``--filter`` / ``--where``.
    ``target_df`` is the table the run writes to, unfiltered: the same table for an
    ``update`` tool, the (possibly still empty) child table for a ``create`` tool.
    The target is kept whole on purpose, so the resume skip in ``ready`` sees every
    row's status regardless of which rows this submission selects.
    """

    source_df: pd.DataFrame
    target_df: pd.DataFrame
    args: ArgsT
    out_dir: Path
    lookup: LookupFn
    write_meta: Callable[..., None]

    @property
    def ready(self) -> pd.DataFrame:
        """The designs this run should submit: rows with a present ``--input-column``,
        minus those this tool already finished unless ``--force``.

        The already-OK skip is the framework's resume-on-rerun. An ``update`` tool
        annotates the source table, so a row is done when its own ``<leaf>_status``
        is ``"OK"``. A ``create`` tool writes children into ``target_df``, so a source
        row is done once any child row naming it as ``parent_name`` is ``"OK"``.
        """
        ready = clean_ready(self.source_df, self.args.input_column)
        if self.args.force:
            return ready
        out_status = status_column(self.out_dir.name)
        if out_status in ready.columns:
            return ready[ready[out_status] != "OK"]
        target = self.target_df
        if out_status in target.columns and PARENT_NAME in target.columns:
            done = target.loc[target[out_status] == "OK", PARENT_NAME].dropna()
            return ready[~ready.index.astype(str).isin(done.astype(str))]
        return ready


BuildManifestFn = Callable[[ManifestCtx[ArgsT]], Sequence[ManifestRow]]


def write_run_meta(out_dir: Path, **fields) -> None:
    """Merge ``fields`` into the run's ``.meta.json`` sidecar, creating it if absent.

    Read-modify-write so additions compose instead of clobbering: the driver seeds
    the base run params, and a ``build_manifest_fn`` adds its own (e.g. root_designs)
    via ``ctx.write_meta`` without wiping what the driver already wrote.
    """
    path = out_dir / RUN_META_FILENAME
    meta: dict = {}
    if path.is_file():
        try:
            meta = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            meta = {}
    meta.update(fields)
    path.write_text(json.dumps(meta, indent=2))


def check_input_column(out_dir: Path, input_column: str) -> None:
    """Refuse a resubmit on a leaf whose sidecar records a different ``--input-column``."""
    path = out_dir / RUN_META_FILENAME
    if not path.is_file():
        return
    try:
        recorded = json.loads(path.read_text()).get("input_column")
    except (OSError, json.JSONDecodeError):
        return
    if recorded is not None and recorded != input_column:
        raise SystemExit(
            f"{out_dir.name!r} was run with --input-column {recorded!r}; this run "
            f"uses {input_column!r}. One leaf takes one input column: pass "
            f"--dir-label to run this tool with a different input."
        )


def run_from_args(
    tool: ToolMetadata,
    build_manifest_fn: BuildManifestFn[ArgsT],
    args: ArgsT,
) -> None:
    """Execute a run from already-parsed args (shared by standalone and ``sapia``)."""
    # Only new_run_dir mints run dirs.
    if not args.run_dir.is_dir():
        raise FileNotFoundError(
            f"run_dir {args.run_dir} does not exist. Create one first: "
            f"sapia new_run --label <label>"
        )

    # Source table (the source rows the manifest iterates over). None for a create
    # tool that starts a new lineage
    src_table = args.table

    with DataManager(args.run_dir) as (dm, (read_frame, save_frame), registry):
        # CREATE reserves a new table in the registry that gets created when collect is called;
        # UPDATE writes back to src_table.
        output_table = registry.resolve_output_table(
            src_table,
            tool.creates_table,
            tool.name,
            getattr(args, "table_label", ""),
        )

        # Dirs (created below, so resolve without the existence guard).
        out_dir = resolve_dir_name(args, output_table, tool, must_exist=False)
        log_dir = out_dir / f"{args.script.stem}_logs"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Write run's base metadata to the sidecar
        check_input_column(out_dir, args.input_column)
        write_run_meta(
            out_dir,
            tool=tool.name,
            input_column=args.input_column,
            dir_label=args.dir_label,
            filter=str(args.filter) if args.filter else None,
            where=args.where,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # A root tool has no source table: give an empty frame (for type security).
        source_df = read_frame(src_table) if src_table else pd.DataFrame()
        # The target frame is the table this run writes to. Needed for create's resume-on-rerun.
        target_df = (
            read_frame(output_table.table_name) if tool.creates_table else source_df
        )

        # Filter
        if args.filter:
            apply_filter = _get_filter_fn_from_module(args.filter)
            source_df = apply_filter(source_df)
        if args.where:
            source_df = apply_where(source_df, args.where)

        # Manifest
        manifest_dir = args.run_dir / ".manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)

        # Stamped per submission: a resubmit on the same table/leaf must not
        # overwrite a manifest that still-pending tasks of an earlier array read.
        leaf = build_tool_leaf(args.script.stem, args.dir_label)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        manifest_base = (
            manifest_dir / f"{output_table.table_name}_{leaf}_{stamp}_manifest.txt"
        )
        ctx = ManifestCtx(
            source_df=source_df,
            target_df=target_df,
            args=args,
            out_dir=out_dir,
            lookup=partial(dm.lookup, source_df),
            write_meta=partial(write_run_meta, out_dir),
        )
        manifest_rows = build_manifest_fn(ctx)

    if not manifest_rows:
        print("No designs to submit.")
        return

    n = len(manifest_rows)
    print(f"Submitting {n} designs")
    print(f"Output:  {out_dir}")
    print(f"Logs:    {log_dir}")

    submit = get_executor(args.executor)
    submit(
        SubmitCtx(
            args=args,
            tool_name=tool.name,
            rows=manifest_rows,
            manifest_base=manifest_base,
            out_dir=out_dir,
            log_dir=log_dir,
        )
    )
