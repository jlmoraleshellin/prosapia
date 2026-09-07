#!/usr/bin/env python3
"""
Collect USalign comparison results into the database.

Scans <run_dir>/USalign/<prefix>_results/ for per-design TSV files written
by usalign.sbatch, and merges the metrics back into the specified database.

Usage:
    sapia collect USalign outputs/RUN \
        --database db1_..._mpnn_seqs \
        --col-a boltz_path --col-b openfold3_path

    sapia collect USalign outputs/RUN \
        --database db1_..._mpnn_seqs \
        --output-prefix boltz_vs_openfold3
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Dict, Iterable

import pandas as pd

from prosapia.core import Collected, CollectArgs, CollectCtx, CollectEach, DesignCtx

USALIGN_COLUMNS = ["TM1", "TM2", "RMSD", "ID1", "ID2", "IDali", "L1", "L2", "Lali"]


class USalignCollectArgs(CollectArgs):
    col_a: str | None
    col_b: str | None
    ref: str | None
    output_prefix: str | None


def _add_usalign_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--col-a",
        type=str,
        default=None,
        help="Database column for structure A (used to derive prefix when "
        "--output-prefix is not set).",
    )
    parser.add_argument(
        "--col-b",
        type=str,
        default=None,
        help="Database column for structure B (used to derive prefix when "
        "--output-prefix is not set).",
    )
    parser.add_argument(
        "--ref",
        type=str,
        default=None,
        help="Fixed reference structure path (used to derive prefix when "
        "--output-prefix is not set, alternative to --col-b).",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=None,
        help="Prefix used during submission. Defaults to "
        "'<col_a_stem>_vs_<col_b_stem>'.",
    )


def _resolve_prefix(args: USalignCollectArgs) -> str:
    if args.output_prefix is not None:
        return args.output_prefix
    if args.col_a is not None and args.col_b is not None:
        return f"{args.col_a.replace('_path', '')}_vs_{args.col_b.replace('_path', '')}"
    if args.col_a is not None and args.ref is not None:
        stem_b = Path(args.ref).stem.split(".")[0]
        return f"{args.col_a.replace('_path', '')}_vs_{stem_b}"
    raise ValueError("Provide --output-prefix, or --col-a with --col-b or --ref.")


def collect_usalign(ctx: CollectCtx) -> CollectEach:
    """Per-design USalign collector.

    USalign's columns are *prefix*-keyed, not leaf-keyed: one output dir hosts
    several named comparisons (e.g. ``boltz_vs_openfold3_TM1``), so it owns all of
    its columns via ``Collected.data`` and sets ``status=None`` to suppress the
    framework's ``<leaf>_status``/``<leaf>_path`` stamp. Each design writes one
    ``<name>.tsv``; re-collecting is idempotent (same tsv -> same values), so this
    relies on the framework's ready iteration rather than a per-prefix resume."""
    prefix = _resolve_prefix(ctx.args)
    results_dir = ctx.out_dir / prefix
    if not results_dir.is_dir():
        raise FileNotFoundError(f"Results dir not found: {results_dir}")

    status_col = f"{prefix}_status"
    sup_path_col = f"{prefix}_sup_path"

    def one(d: DesignCtx) -> Iterable[Collected]:
        tsv_path = results_dir / f"{d.name}.tsv"

        if not tsv_path.is_file():
            yield Collected(status=None, data={status_col: "missing"})
            return

        result_df = pd.read_csv(tsv_path, sep="\t")
        if result_df.empty:
            yield Collected(status=None, data={status_col: "error: empty tsv"})
            return

        row_data = result_df.iloc[0]
        status = str(row_data["status"])
        data: Dict[str, Any] = {status_col: status}

        if status == "OK":
            data[sup_path_col] = row_data["sup_path"]
            for col in USALIGN_COLUMNS:
                if col in row_data.index:
                    try:
                        data[f"{prefix}_{col}"] = float(row_data[col])
                    except (ValueError, TypeError):
                        data[f"{prefix}_{col}"] = pd.NA

        yield Collected(status=None, data=data)

    return one
