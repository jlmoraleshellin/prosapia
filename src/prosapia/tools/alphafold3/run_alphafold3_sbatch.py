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
from prosapia.utils import group_by_sequence, select_chains


class AlphaFold3Args(CommonArgs):
    shard_size: int
    start_at_column: str
    model_seeds: list[int]
    chains: str | None
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


def _add_af3_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--shard-size",
        type=int,
        default=10,
        help="Number of JSON inputs per shard directory. Defaults to 10.",
    )
    parser.add_argument(
        "--start-at-column",
        type=str,
        default="prebundle_length",
        help="Column whose value determines how many N-terminal residues to trim. "
        "Use 'none' to use the full sequence. Defaults to 'prebundle_length'.",
    )
    parser.add_argument(
        "--model-seeds",
        type=int,
        nargs="+",
        default=[42],
        help="Model seeds for AF3 predictions. Defaults to [42].",
    )
    parser.add_argument(
        "--chains",
        type=str,
        default=None,
        metavar="A:D",
        help="Chains to predict, in the chain mini-language (':' inclusive letter "
        "range, ',' separates): e.g. 'A:D' -> A, B, C, D. Selects those chains from "
        "the input sequence; letters beyond the sequence's chain count are dropped. "
        "Default: predict every chain in the sequence.",
    )
    parser.add_argument(
        "--no-msa",
        action="store_true",
        help="Write empty MSA fields in the input JSONs, skipping MSA search.",
    )


def build_af3_manifest(ctx: ManifestCtx[AlphaFold3Args]):
    json_dir = ctx.out_dir / "af3_inputs"
    json_dir.mkdir(parents=True, exist_ok=True)

    ready = ctx.ready

    start_at_col: str | None = ctx.args.start_at_column
    if start_at_col and start_at_col.lower() == "none":
        start_at_col = None

    json_paths: list[Path] = []
    for name in ready.index:
        name = cast(str, name)
        sequence = str(ready.at[name, ctx.args.input_column])
        chain_map = select_chains(sequence, ctx.args.chains)
        if start_at_col:
            start_at = int(ready.at[name, start_at_col])  # type: ignore
            chain_map = {c: seq[start_at:] for c, seq in chain_map.items()}
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
