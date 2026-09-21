#!/usr/bin/env python3
"""
Submit a SLURM array job to run AlphaFold3 predictions on MPNN-designed sequences.

Creates individual AF3 JSON input files, groups them into shard directories,
and submits a sbatch array where each task runs AF3 on a whole shard
(via --input_dir inside a singularity container).

Chains are derived per-sequence from the MPNN chainbreak syntax (``/``-separated
chains): chains sharing a sequence collapse into one homo-oligomer entity, distinct
sequences become separate hetero-oligomer entities. ``--chains`` narrows which
chains to predict (mini-language, e.g. ``A:D``).

Usage:
    sapia run alphafold3 outputs/20260420_123035_grow_hairpin --table table1_..._proteinmpnn
    sapia run alphafold3 outputs/20260420_123035_grow_hairpin --table table1_..._proteinmpnn --shard-size 20
"""

import json
from argparse import ArgumentParser
from pathlib import Path
from shutil import copy2
from typing import cast

from prosapia.core import CommonArgs, ManifestCtx
from prosapia.utils import (
    add_chains_and_positions_args,
    build_chain_map,
    group_by_sequence,
)


class AlphaFold3Args(CommonArgs):
    shard_size: int
    model_seeds: list[int]
    chains: str | None
    positions: str | None
    no_msa: bool


def write_af3_json(
    json_path: Path,
    name: str,
    chain_map: dict[str, str],
    model_seeds: list[int],
    *,
    no_msa: bool = False,
) -> None:
    """Write one AF3 JSON input.

    Chains sharing a sequence collapse into one protein entity with a multi-letter
    ``id`` (homo-oligomer); distinct sequences become separate entities
    (hetero-oligomer).
    """
    sequences: list[dict] = []
    for letters, seq in group_by_sequence(chain_map):
        protein: dict = {
            "id": letters,
            "sequence": seq,
        }
        if no_msa:
            protein["unpairedMsa"] = ""
            protein["pairedMsa"] = ""
            protein["templates"] = []
        sequences.append({"protein": protein})
    payload = {
        "name": name,
        "modelSeeds": model_seeds,
        "sequences": sequences,
        "dialect": "alphafold3",
        "version": 1,
    }
    json_path.write_text(json.dumps(payload, indent=2))


def add_run_af3_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--shard-size",
        type=int,
        default=10,
        help="Number of JSON inputs per shard directory. Defaults to 10.",
    )
    parser.add_argument(
        "--model-seeds",
        type=int,
        nargs="+",
        default=[42],
        help="Model seeds for AF3 predictions. Defaults to [42].",
    )
    add_chains_and_positions_args(parser)
    parser.add_argument(
        "--no-msa",
        action="store_true",
        help="Write empty MSA fields in the input JSONs, skipping MSA search.",
    )


def build_af3_manifest(ctx: ManifestCtx[AlphaFold3Args]):
    json_dir = ctx.out_dir / "af3_inputs"
    json_dir.mkdir(parents=True, exist_ok=True)

    ready = ctx.ready

    json_paths: list[Path] = []
    for name in ready.index:
        name = cast(str, name)
        sequence = str(ready.at[name, ctx.args.input_column])
        chain_map = build_chain_map(
            sequence, ctx.args.chains, ctx.args.positions, ctx.lookup, name
        )
        json_path = json_dir / f"{name}.json"
        write_af3_json(
            json_path,
            name,
            chain_map,
            ctx.args.model_seeds,
            no_msa=ctx.args.no_msa,
        )
        json_paths.append(json_path)

    shards_dir = ctx.out_dir / "af3_shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(json_paths), ctx.args.shard_size):
        shard_idx = i // ctx.args.shard_size
        shard = shards_dir / f"shard_{shard_idx}"
        shard.mkdir(parents=True, exist_ok=True)
        for json_path in json_paths[i : i + ctx.args.shard_size]:
            copy2(json_path, shard / json_path.name)
        manifest_rows.append((str(shard),))

    return manifest_rows
