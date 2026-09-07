#!/usr/bin/env python3
"""
Submit a SLURM array job to run boltz predictions on MPNN-designed sequences.

Reads sequences from an MPNN database, writes one boltz YAML input per sequence,
groups them into shard directories, and submits a sbatch array where each task
runs boltz on a whole shard (optionally on multiple GPUs via --devices).

The template CIF, chain layout, and number of subunits are hardcoded at the
top of this file -- edit them there.

Usage:
    sapia run boltz outputs/20260420_123035_grow_hairpin --database db1_..._mpnn_seqs
    sapia run boltz outputs/20260420_123035_grow_hairpin --database db1_..._mpnn_seqs --shard-size 20 --devices 4
"""

import os
from argparse import ArgumentParser
from pathlib import Path
from shutil import copy2
from typing import cast

from dotenv import load_dotenv

from prosapia.core import CommonArgs, ManifestCtx

load_dotenv()  # Load environment variables from .env file

# ------------ Boltz template config -----------------------------------------
N_SUBUNITS = 11
CHAIN_IDS = list("ABCDEFGHIJK")[:N_SUBUNITS]
TEMPLATE_CIF = os.getenv("TEMPLATE_CIF", "")  # set in .env
TEMPLATE_THRESHOLD = os.getenv("TEMPLATE_THRESHOLD", 2.0)  # set in .env
USE_MSA = os.getenv("USE_MSA", False)  # set in .env
# -----------------------------------------------------------------------------


class BoltzArgs(CommonArgs):
    shard_size: int
    devices: int


def _format_chain_list(ids: list[str]) -> str:
    """Render ['A', 'B', ...] as '[A, B, ...]' for boltz YAML."""
    return "[" + ", ".join(ids) + "]"


def write_boltz_yaml(yaml_path: Path, sequence: str) -> None:
    """Write a single boltz input YAML."""
    sequence = sequence.split("/", 1)[0]
    chain_list = _format_chain_list(CHAIN_IDS)
    msa_line = "" if USE_MSA else "      msa: empty\n"
    yaml_text = (
        "version: 1\n"
        "sequences:\n"
        "  - protein:\n"
        f"      id: {chain_list}\n"
        f"      sequence: {sequence}\n"
        f"{msa_line}"
        "templates:\n"
        f"  - cif: {TEMPLATE_CIF}\n"
        f"    chain_id: {chain_list}\n"
        f"    template_id: {chain_list}\n"
        f"    force: true\n"
        f"    threshold: {TEMPLATE_THRESHOLD}\n"
    )
    yaml_path.write_text(yaml_text)


def _add_boltz_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--shard-size",
        type=int,
        default=10,
        help="Number of YAML inputs per shard directory. Defaults to 10.",
    )
    parser.add_argument(
        "--devices",
        type=int,
        default=1,
        help="Number of GPUs boltz uses per task (--devices). "
        "Automatically sets --gpus-per-task to match unless explicitly overridden. "
        "Defaults to 1.",
    )


def build_boltz_manifest(ctx: ManifestCtx[BoltzArgs]):
    if ctx.args.devices > 1:
        ctx.args.gpus_per_task = ctx.args.devices

    yaml_dir = ctx.out_dir / "boltz_inputs"
    yaml_dir.mkdir(parents=True, exist_ok=True)

    yaml_paths: list[Path] = []
    for name in ctx.ready.index:
        name = cast(str, name)
        sequence = str(ctx.ready.at[name, ctx.args.input_column])
        yaml_path = yaml_dir / f"{name}.yml"
        write_boltz_yaml(yaml_path, sequence)
        yaml_paths.append(yaml_path)

    shards_dir = ctx.out_dir / "boltz_shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(yaml_paths), ctx.args.shard_size):
        shard_idx = i // ctx.args.shard_size
        shard = shards_dir / f"shard_{shard_idx}"
        shard.mkdir(parents=True, exist_ok=True)
        for yaml_path in yaml_paths[i : i + ctx.args.shard_size]:
            copy2(yaml_path, shard / yaml_path.name)
        manifest_rows.append((str(shard), str(ctx.args.devices)))

    return manifest_rows
