#!/usr/bin/env python3
"""
Submit a SLURM array job to run AlphaFold3 predictions on MPNN-designed sequences.

Creates individual AF3 JSON input files, groups them into shard directories,
and submits a sbatch array where each task runs AF3 on a whole shard
(via --input_dir inside a singularity container).

Requires ``n_subunits`` column available up the input db's lineage
(resolved via ``DataManager.lookup``).

Usage:
    sapia run alphafold3 outputs/20260420_123035_grow_hairpin --database db1_..._mpnn_seqs
    sapia run alphafold3 outputs/20260420_123035_grow_hairpin --database db1_..._mpnn_seqs --shard-size 20
"""

import json
import string
from argparse import ArgumentParser
from pathlib import Path
from shutil import copy2
from typing import cast

from prosapia.core import CommonArgs, ManifestCtx


class AlphaFold3Args(CommonArgs):
    shard_size: int
    start_at_column: str
    model_seeds: list[int]
    n_subunits: int | None
    no_msa: bool


def write_af3_json(
    json_path: Path,
    name: str,
    sequence: str,
    chain_ids: list[str],
    model_seeds: list[int],
    *,
    no_msa: bool = False,
) -> None:
    protein: dict = {
        "id": chain_ids,
        "sequence": sequence,
    }
    if no_msa:
        protein["unpairedMsa"] = ""
        protein["pairedMsa"] = ""
        protein["templates"] = []
    payload = {
        "name": name,
        "modelSeeds": model_seeds,
        "sequences": [{"protein": protein}],
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
        "--n-subunits",
        type=int,
        default=None,
        help="Fixed number of subunits for all designs. "
        "When set, overrides the 'n_subunits' DB column.",
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
        sequence = str(ready.at[name, ctx.args.input_column]).split("/", 1)[0]
        if start_at_col:
            start_at = int(ready.at[name, start_at_col])  # type: ignore
            sequence = sequence[start_at:]
        n_subunits = ctx.args.n_subunits or int(ctx.lookup(name, "n_subunits"))
        chain_ids = list(string.ascii_uppercase[:n_subunits])
        json_path = json_dir / f"{name}.json"
        write_af3_json(
            json_path,
            name,
            sequence,
            chain_ids,
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
