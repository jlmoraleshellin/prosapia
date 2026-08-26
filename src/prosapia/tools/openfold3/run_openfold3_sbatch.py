#!/usr/bin/env python3
"""
Submit a SLURM array job to run OpenFold3 predictions on MPNN-designed sequences.

Reads sequences from an MPNN database, trims N-terminal residues based on
--start-at-column, groups them into JSON query files (one per SLURM task),
generates a shared runner YAML for device config, and submits an sbatch array.

Requires ``n_subunits`` and (optionally) ``prebundle_length`` columns in the
input database. Run ``collect_worms_metadata.py`` first to propagate them
from the worms database.

Usage:
    python run_openfold3_batch.py outputs/20260420_123035_grow_hairpin
    python run_openfold3_batch.py outputs/20260420_123035_grow_hairpin --queries-per-task 20 --devices 4
"""

import json
import string
from argparse import ArgumentParser
from pathlib import Path
from typing import cast

import yaml

from prosapia.core import CommonArgs, ManifestCtx


class OpenFold3Args(CommonArgs):
    queries_per_task: int
    devices: int
    start_at_column: str
    n_subunits: int | None


def write_openfold_json_query(
    json_path: Path,
    queries: list[tuple[str, str, list[str]]],
) -> None:
    """Write a multi-query JSON file for OpenFold3.

    Parameters
    ----------
    queries : list of (name, sequence, chain_ids) tuples
    """
    payload: dict = {"queries": {}}
    for name, sequence, chain_ids in queries:
        payload["queries"][name] = {
            "chains": [
                {
                    "molecule_type": "protein",
                    "chain_ids": chain_ids,
                    "sequence": sequence,
                }
            ]
        }
    json_path.write_text(json.dumps(payload, indent=2))


def write_runner_yaml(runner_path: Path, devices: int) -> None:
    runner = {
        "pl_trainer_args": {
            "devices": devices,
        }
    }
    runner_path.write_text(yaml.dump(runner, default_flow_style=False))


def _add_openfold3_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--queries-per-task",
        type=int,
        default=10,
        help="Number of queries per JSON file (i.e. per SLURM task). Defaults to 10.",
    )
    parser.add_argument(
        "--devices",
        type=int,
        default=1,
        help="Number of GPUs per task. "
        "Automatically sets --gpus-per-task to match unless explicitly overridden. "
        "Defaults to 1.",
    )
    parser.add_argument(
        "--start-at-column",
        type=str,
        default="prebundle_length",
        help="Column whose value determines how many N-terminal residues to trim. "
        "Use 'none' to use the full sequence. Defaults to 'prebundle_length'.",
    )
    parser.add_argument(
        "--n-subunits",
        type=int,
        default=None,
        help="Fixed number of subunits for all designs. "
        "When set, overrides the 'n_subunits' DB column.",
    )


def build_openfold3_manifest(ctx: ManifestCtx[OpenFold3Args]) -> list[tuple[str, ...]]:
    df, args, out_dir, lookup = ctx.df, ctx.args, ctx.out_dir, ctx.lookup
    if args.devices > 1:
        args.gpus_per_task = args.devices

    json_dir = out_dir / "openfold3_queries"
    json_dir.mkdir(parents=True, exist_ok=True)

    ready = df[
        df[args.input_column].notna()
        & (df[args.input_column] != "")
        & ~df.index.astype(str).str.endswith("_f0")
    ]

    output_status_col = f"{out_dir.name}_status"
    if output_status_col in ready.columns:
        ready = ready[ready[output_status_col] != "OK"]

    start_at_col: str | None = args.start_at_column
    if start_at_col and start_at_col.lower() == "none":
        start_at_col = None

    queries: list[tuple[str, str, list[str]]] = []
    for name in ready.index:
        name = cast(str, name)
        sequence = str(ready.at[name, args.input_column]).split("/", 1)[0]
        if start_at_col:
            start_at = int(ready.at[name, start_at_col])  # type: ignore
            sequence = sequence[start_at:]
        n_subunits = args.n_subunits or int(lookup(name, "n_subunits"))
        chain_ids = list(string.ascii_uppercase[:n_subunits])
        queries.append((name, sequence, chain_ids))

    runner_path = out_dir / "runner.yml"
    write_runner_yaml(runner_path, args.devices)

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(queries), args.queries_per_task):
        batch = queries[i : i + args.queries_per_task]
        task_idx = i // args.queries_per_task
        json_path = json_dir / f"query_{task_idx}.json"
        write_openfold_json_query(json_path, batch)
        manifest_rows.append(tuple(map(str, (json_path, runner_path))))

    return manifest_rows
