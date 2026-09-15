#!/usr/bin/env python3
"""
Submit a SLURM array job to run OpenFold3 predictions on MPNN-designed sequences.

Reads sequences from an MPNN table, groups them into JSON query files (one per
SLURM task), generates a shared runner YAML for device config, and submits an
sbatch array.

Chains are derived per-sequence from the MPNN chainbreak syntax (``/``-separated
chains): chains sharing a sequence collapse into one homo-oligomer chain block,
distinct sequences become separate hetero-oligomer blocks. ``--chains`` narrows
which chains to predict (mini-language, e.g. ``A:D``). ``--positions`` selects
which residues of each chain to keep (e.g. ``--positions '{prebundle_length+1}:'``
trims an N-terminal prefix).

Usage:
    sapia run openfold3 outputs/20260420_123035_grow_hairpin --table table1
    sapia run openfold3 outputs/20260420_123035_grow_hairpin --table table1 --queries-per-task 20 --devices 4
"""

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import cast

import yaml

from prosapia.core import CommonArgs, ManifestCtx
from prosapia.utils import (
    add_chains_and_positions_args,
    add_devices_arg,
    build_chain_map,
    group_by_sequence,
    maybe_set_gpus_per_task,
)


class OpenFold3Args(CommonArgs):
    queries_per_task: int
    devices: int
    chains: str | None
    positions: str | None


def write_openfold_json_query(
    json_path: Path,
    queries: list[tuple[str, dict[str, str]]],
) -> None:
    """Write a multi-query JSON file for OpenFold3.

    Parameters
    ----------
    queries : list of (name, chain_map) tuples, where chain_map is an ordered
        ``{chain_letter: sequence}``. Chains sharing a sequence collapse into one
        chain block (homo-oligomer); distinct sequences become separate blocks
        (hetero-oligomer).
    """
    payload: dict = {"queries": {}}
    for name, chain_map in queries:
        payload["queries"][name] = {
            "chains": [
                {
                    "molecule_type": "protein",
                    "chain_ids": letters,
                    "sequence": seq,
                }
                for letters, seq in group_by_sequence(chain_map)
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


def add_openfold3_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--queries-per-task",
        type=int,
        default=10,
        help="Number of queries per JSON file (i.e. per SLURM task). Defaults to 10.",
    )
    add_devices_arg(parser)
    add_chains_and_positions_args(parser)


def build_openfold3_manifest(ctx: ManifestCtx[OpenFold3Args]) -> list[tuple[str, ...]]:
    maybe_set_gpus_per_task(ctx.args)

    json_dir = ctx.out_dir / "openfold3_queries"
    json_dir.mkdir(parents=True, exist_ok=True)

    ready = ctx.ready

    queries: list[tuple[str, dict[str, str]]] = []
    for name in ready.index:
        name = cast(str, name)
        sequence = str(ready.at[name, ctx.args.input_column])
        chain_map = build_chain_map(
            sequence, ctx.args.chains, ctx.args.positions, ctx.lookup, name
        )
        queries.append((name, chain_map))

    runner_path = ctx.out_dir / "runner.yml"
    write_runner_yaml(runner_path, ctx.args.devices)

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(queries), ctx.args.queries_per_task):
        batch = queries[i : i + ctx.args.queries_per_task]
        task_idx = i // ctx.args.queries_per_task
        json_path = json_dir / f"query_{task_idx}.json"
        write_openfold_json_query(json_path, batch)
        manifest_rows.append(tuple(map(str, (json_path, runner_path))))

    return manifest_rows
