# PYTHON_ARGCOMPLETE_OK
"""Generic SLURM array submission.

Every batch-submission script delegates here, supplying a ``build_manifest_fn``
(filters the db, returns one manifest row per array task) and optionally an
``add_extra_args_fn`` for extra CLI flags. An optional ``--filter`` module's
``apply_filter(df) -> df`` runs before the manifest is built.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
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
from .data_manager import Database, DataManager, LookupFn, RegistryManager, filter_ready
from .naming import (
    RUN_META_FILENAME,
    resolve_dir_name,
    status_column,
)

if TYPE_CHECKING:
    from .tool import ToolMetadata

load_dotenv()

SLURM_MAX_ARRAY_SIZE = int(os.getenv("SLURM_MAX_ARRAY_SIZE", 1000))

# Sourced by every tool's .sbatch (via $SAPIA_PRELUDE) for shared task scaffolding. See core/sbatch/sapia_task_prelude.sh.
PRELUDE_PATH = Path(__file__).parent / "sbatch" / "sapia_task_prelude.sh"


## ARGPARSER
class CommonArgs(Namespace):
    run_dir: Path
    database: str | None
    sbatch_script: Path
    input_column: str
    dir_label: str
    db_label: str
    filter: Path | None
    max_concurrent: int
    partitions: str | None
    account: str | None
    max_gpu_fraction: float
    gpus_per_task: int
    force: bool


def _add_sbatch_args(
    parser: ArgumentParser,
    default_sbatch: str,
    default_input_column: str,
) -> None:
    """Add the SLURM-array flags shared by every run parser (standalone or ``sapia``)."""
    parser.add_argument(
        "-s",
        "--sbatch-script",
        type=Path,
        default=default_sbatch,
        help=f"Path to the sbatch script. Defaults to '{default_sbatch}'.",
    )
    parser.add_argument(
        "-i",
        "--input-column",
        type=str,
        default=default_input_column,
        help=f"Input column from database. \
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
        "-c",
        "--max-concurrent",
        type=int,
        default=40,
        help="Max concurrent SLURM array tasks. Defaults to 40.",
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
        help="GPUs requested per array task (--gres=gpu:N). Can be 0 for CPU-only tasks."
        "Scripts like run_boltz_batch.py set this automatically from --devices. "
        "Defaults to 1.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-submit designs this tool already completed (skips the resume "
        "filter that drops rows whose <leaf>_status is already 'OK').",
    )


def sbatch_argparser(
    description: str,
    default_sbatch: str,
    default_input_column: str,
    require_database: bool = True,
) -> ArgumentParser:
    parser = ArgumentParser(
        parents=[base_parser(require_database=require_database)],
        description=description,
    )
    _add_sbatch_args(parser, default_sbatch, default_input_column)
    return parser


def build_run_parser(
    metadata: "ToolMetadata",
    default_sbatch: str,
    default_input_column: str,
    add_extra_args_fn: AddArgsFn | None = None,
) -> ArgumentParser:
    """Build a reusable (``add_help=False``) parent parser holding every run flag for
    a tool: base args + batch flags + ``--db-label`` (create tools) + tool extras.

    Used both by ``submit_sbatch_array`` (as the sole parent of a standalone parser)
    and by the ``sapia`` CLI (as ``parents=[...]`` of each ``run <tool>`` subparser), so
    a single ``argcomplete`` call at the top sees the full argument tree.
    """
    parser = ArgumentParser(
        add_help=False,
        parents=[base_parser(require_database=not metadata.creates_db)],
    )
    _add_sbatch_args(parser, default_sbatch, default_input_column)
    if metadata.creates_db:
        parser.add_argument(
            "--db-label",
            type=str,
            default="",
            help="Optional label for the child database this run creates "
            "(append rule: db<gen>_<parent_label>_<db_label>). Omit for an "
            "unlabelled child (db<gen>); pass one to disambiguate a fork.",
        )
    if add_extra_args_fn is not None:
        add_extra_args_fn(parser)
    return parser


## OUTPUT DATABASE RESOLUTION
def resolve_output_db(
    registry: RegistryManager,
    tool: ToolMetadata,
    src_db: str | None,
    db_label: str = "",
) -> Database:
    """Resolve the db a run writes to: reserve a child/root for create, else return ``src_db``."""
    if not tool.creates_db:
        if src_db is None:
            raise ValueError(
                f"Update tool {tool.name!r} annotates an existing db in place and "
                f"requires --database; none was given."
            )
        return registry.get_database(src_db)
    output_db = registry.derive_new_db(src_db, db_label)
    output_db.tool_name = tool.name  # provenance: the tool that creates this db
    registry.register_database(output_db)
    return output_db


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


## MANIFEST BUILDING AND SBATCH SUBMISSION
ManifestRow = Sequence[str]
AddArgsFn = Callable[[ArgumentParser], None]

ArgsT = TypeVar("ArgsT", bound=CommonArgs)


@dataclass
class ManifestCtx(Generic[ArgsT]):
    """Inputs a manifest builder may read (frame, args, out_dir, lookup)."""

    df: pd.DataFrame
    args: ArgsT
    out_dir: Path
    lookup: LookupFn

    @property
    def ready(self) -> pd.DataFrame:
        """The designs this run should submit: rows with a present ``--input-column``,
        minus those this tool already finished (``<leaf>_status == "OK"``) unless
        ``--force``.

        The already-OK skip is the framework's resume-on-rerun: it fires only when
        the output status column is present in the source frame, i.e. for ``update``
        tools (which annotate the same db). For ``create`` tools the column lives in
        the child db, so the skip is a no-op and every ready design is submitted. #TODO maybe check child db too?
        """
        ready = filter_ready(self.df, self.args.input_column)
        out_status = status_column(self.out_dir.name)
        if not self.args.force and out_status in ready.columns:
            ready = ready[ready[out_status] != "OK"]
        return ready


BuildManifestFn = Callable[[ManifestCtx[ArgsT]], Sequence[ManifestRow]]


def _query_partition_gpus(partition: str) -> int:
    """Query total GPU count for a SLURM partition via ``sinfo``."""
    result = subprocess.run(
        ["sinfo", "-p", partition, "-h", "-N", "-o", "%G"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"sinfo failed for partition {partition!r}: {result.stderr.strip()}\n"
            f"Specify GPU counts explicitly: --partitions {partition}:<gpu_count>"
        )
    total = 0
    for line in result.stdout.strip().splitlines():
        for entry in line.split(","):
            if entry.startswith("gpu"):
                parts = entry.split(":")
                total += int(parts[-1])
    if total == 0:
        raise RuntimeError(
            f"No GPUs found in partition {partition!r}. "
            f"Specify GPU counts explicitly: --partitions {partition}:<gpu_count>"
        )
    return total


def _write_manifest(path: Path, rows: Sequence[ManifestRow]) -> None:
    """Manifest is tab-separated"""
    with open(path, "w") as f:
        for row in rows:
            f.write("\t".join(str(v) for v in row) + "\n")


def write_run_meta(out_dir: Path, metadata: ToolMetadata, args: CommonArgs) -> None:
    """Record this run's parameters into the out_dir sidecar"""
    meta = {
        "tool": metadata.name,
        "input_column": args.input_column,
        "dir_label": args.dir_label,
        "filter": str(args.filter) if args.filter else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / RUN_META_FILENAME).write_text(json.dumps(meta, indent=2))


def _submit_array(
    args: CommonArgs,
    manifest: Path,
    n_tasks: int,
    log_dir: Path,
    out_dir: Path,
    max_concurrent: int,
    partition: str | None = None,
) -> None:
    cmd = [
        "sbatch",
        f"--account={args.account}" if args.account else "",
        f"--array=1-{n_tasks}%{max_concurrent}",
        f"--partition={partition}" if partition else "",
        f"--gres=gpu:{args.gpus_per_task}" if args.gpus_per_task > 0 else "",
        f"--output={log_dir}/{args.sbatch_script.stem}_%A_%a.out",
        f"--error={log_dir}/{args.sbatch_script.stem}_%A_%a.err",
        str(args.sbatch_script),
        str(manifest),
        str(out_dir),
    ]
    cmd = [c for c in cmd if c]  # Remove empty arguments
    print("Submitting:", " ".join(cmd))
    result = subprocess.run(
        cmd,
        env={**os.environ, "SAPIA_PRELUDE": str(PRELUDE_PATH)},
    )
    if result.returncode != 0:
        raise RuntimeError(f"sbatch exited {result.returncode}")


def _submit_chunked(
    args: CommonArgs,
    rows: Sequence[ManifestRow],
    manifest_base: Path,
    log_dir: Path,
    out_dir: Path,
    max_concurrent: int,
    partition: str | None = None,
) -> None:
    """Split rows into chunks of SLURM_MAX_ARRAY_SIZE, write a manifest for
    each chunk, and submit separate array jobs."""
    chunks = [
        rows[i : i + SLURM_MAX_ARRAY_SIZE]
        for i in range(0, len(rows), SLURM_MAX_ARRAY_SIZE)
    ]

    for chunk_idx, chunk in enumerate(chunks):
        if len(chunks) == 1:
            manifest = manifest_base
        else:
            manifest = manifest_base.with_stem(f"{manifest_base.stem}_{chunk_idx}")
        _write_manifest(manifest, chunk)

        if partition or len(chunks) > 1:
            parts = []
            if partition:
                parts.append(partition)
            if len(chunks) > 1:
                parts.append(f"chunk {chunk_idx + 1}/{len(chunks)}")
            print(f"[{', '.join(parts)}]")

        _submit_array(
            args,
            manifest,
            len(chunk),
            log_dir,
            out_dir,
            max_concurrent,
            partition,
        )


def _submit_multi_partition(
    args: CommonArgs,
    rows: Sequence[ManifestRow],
    manifest_base: Path,
    log_dir: Path,
    out_dir: Path,
) -> None:
    """Submit one SLURM array per partition, each capped at a GPU fraction.
    Each partition's share is further chunked to respect SLURM_MAX_ARRAY_SIZE."""

    def parse_partitions(raw: str) -> list[tuple[str, int | None]]:
        """Parse ``'part1[:gpus],part2[:gpus]'`` into (name, gpu_count | None)."""
        result: list[tuple[str, int | None]] = []
        for token in raw.split(","):
            if ":" in token:
                name, count = token.rsplit(":", 1)
                result.append((name, int(count)))
            else:
                result.append((token, None))
        return result

    parsed = parse_partitions(args.partitions)  # type: ignore[arg-type]

    partition_caps: list[tuple[str, int]] = []
    for name, gpu_count in parsed:
        if gpu_count is None:
            gpu_count = _query_partition_gpus(name)
        cap = max(1, int(gpu_count * args.max_gpu_fraction) // args.gpus_per_task)
        partition_caps.append((name, cap))

    n_tasks = len(rows)
    n_parts = len(partition_caps)
    chunk = n_tasks // n_parts
    remainder = n_tasks % n_parts
    start = 0
    for i, (partition, cap) in enumerate(partition_caps):
        size = chunk + (1 if i < remainder else 0)
        if size == 0:
            continue
        partition_rows = rows[start : start + size]
        part_manifest = manifest_base.with_stem(f"{manifest_base.stem}_{partition}")
        _submit_chunked(
            args,
            partition_rows,
            part_manifest,
            log_dir,
            out_dir,
            cap,
            partition,
        )
        start += size


def run_from_args(
    metadata: ToolMetadata,
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

    # Source database (the source rows the manifest iterates over). None for a create
    # tool that starts a new lineage
    src_db = args.database

    with DataManager(args.run_dir) as (dm, (read_frame, save_frame), registry):
        # CREATE reserves a new db in the registry that gets created when collect is called;
        # UPDATE writes back to src_db.
        output_db = resolve_output_db(
            registry, metadata, src_db or None, getattr(args, "db_label", "")
        )

        # Dirs (created below, so resolve without the existence guard).
        out_dir = resolve_dir_name(args, output_db, metadata, must_exist=False)
        log_dir = out_dir / f"{args.sbatch_script.stem}_logs"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        write_run_meta(out_dir, metadata, args)

        # A root tool has no source db: give an empty frame (for type security).
        df = read_frame(src_db) if src_db else pd.DataFrame()

        # Filter
        if args.filter:
            apply_filter = _get_filter_fn_from_module(args.filter)
            df = apply_filter(df)

        # Manifest
        manifest_dir = args.run_dir / ".manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)

        manifest_base = manifest_dir / f"{args.sbatch_script.stem}_manifest.txt"
        ctx = ManifestCtx(
            df=df,
            args=args,
            out_dir=out_dir,
            lookup=partial(dm.lookup, df),
        )
        manifest_rows = build_manifest_fn(ctx)

    if not manifest_rows:
        print("No designs to submit.")
        return

    n = len(manifest_rows)
    print(f"Submitting {n} designs")
    print(f"Output:  {out_dir}")
    print(f"Logs:    {log_dir}")

    # Submit array jobs, chunking into groups of SLURM_MAX_ARRAY_SIZE.
    if args.partitions:
        _submit_multi_partition(args, manifest_rows, manifest_base, log_dir, out_dir)
    else:
        _submit_chunked(
            args,
            manifest_rows,
            manifest_base,
            log_dir,
            out_dir,
            args.max_concurrent,
        )
