#!/usr/bin/env python3
"""
Submit a SLURM array job to run boltz predictions on MPNN-designed sequences.

Reads sequences from an MPNN table, writes one boltz YAML input per sequence,
groups them into shard directories, and submits a sbatch array where each task
runs boltz on a whole shard (optionally on multiple GPUs via --devices).

Chains are derived per-sequence from the MPNN chainbreak syntax (``/``-separated
chains): chains sharing a sequence collapse into one homo-oligomer entity, distinct
sequences become separate hetero-oligomer entities. ``--chains`` narrows which
chains to predict (mini-language, e.g. ``A:D``). Only the template CIF has a site
default, via the TEMPLATE_CIF environment variable.

Manifest layout: the only genuinely per-task field is the shard directory. Every
run-wide boltz CLI option (``--devices``, ``--use_msa_server``, ...) is collapsed
into a single space-separated ``extra`` field (see ``_boltz_extra``), which the
sbatch drops unquoted into the ``boltz predict`` argv. Adding a run-wide flag
means extending ``_boltz_extra``, not adding a manifest column.

Usage:
    sapia run boltz outputs/20260420_123035_grow_hairpin --table table1
    sapia run boltz outputs/20260420_123035_grow_hairpin --table table1 --shard-size 20 --devices 4
"""

import os
from argparse import ArgumentParser
from pathlib import Path
from shutil import copy2
from typing import cast

from dotenv import load_dotenv

from prosapia.core import CommonArgs, ManifestCtx
from prosapia.utils import group_by_sequence, select_chains

load_dotenv()  # Load environment variables from .env file

# ------------ Boltz template config -----------------------------------------
TEMPLATE_CIF = os.getenv("TEMPLATE_CIF", "")  # set in .env
# -----------------------------------------------------------------------------


class BoltzArgs(CommonArgs):
    shard_size: int
    devices: int
    use_msa_server: bool
    use_template: bool
    template_cif: str
    template_threshold: float
    chains: str | None


def _format_id_list(letters: list[str]) -> str:
    """Render ['A', 'B', ...] as '[A, B, ...]' for boltz YAML."""
    return "[" + ", ".join(letters) + "]"


def write_boltz_yaml(yaml_path: Path, sequence: str, args: BoltzArgs) -> None:
    """Write a single boltz input YAML.

    Chains come from the proteinmpnn ``/``-chainbreak ``sequence`` (optionally
    narrowed by ``--chains``). Chains sharing a sequence collapse into one entity
    with a multi-letter ``id`` (homo-oligomer); distinct sequences become separate
    ``- protein:`` entities (hetero-oligomer).
    """
    chain_map = select_chains(sequence, args.chains)

    entities = ["  - protein:\n"
                f"      id: {_format_id_list(letters)}\n"
                f"      sequence: {seq}\n"
                + ("" if args.use_msa_server else "      msa: empty\n")
                for letters, seq in group_by_sequence(chain_map)]

    # Templates apply across every predicted chain (top-level block, after sequences).
    template_id_list = _format_id_list(list(chain_map))
    template_line = (
        (
            "templates:\n"
            f"  - cif: {args.template_cif}\n"
            f"    chain_id: {template_id_list}\n"
            f"    template_id: {template_id_list}\n"
            f"    force: true\n"
            f"    threshold: {args.template_threshold}\n"
        )
        if args.use_template
        else ""
    )
    yaml_text = "version: 1\nsequences:\n" + "".join(entities) + template_line
    yaml_path.write_text(yaml_text)


def _boltz_extra_cli_args(args: BoltzArgs) -> str:
    """Run-wide `boltz predict` args (same for every shard), joined space-separated."""
    parts = [f"--devices {args.devices}"]
    if args.use_msa_server:
        parts.append("--use_msa_server")
    return " ".join(parts)


def add_boltz_args(parser: ArgumentParser) -> None:
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
    parser.add_argument(
        "--use-msa-server",
        action="store_true",
        help="Use MSA information in the boltz input YAML.",
    )
    parser.add_argument(
        "--use-template",
        action="store_true",
        help="Use template information in the boltz input YAML.",
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
        "--template-cif",
        type=str,
        default=TEMPLATE_CIF,
        help="Path to template CIF file. Defaults to TEMPLATE_CIF environment variable.",
    )
    parser.add_argument(
        "--template-threshold",
        type=float,
        default=2.0,
        help="Template threshold for boltz input YAML. Defaults to 2.0.",
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
        write_boltz_yaml(yaml_path, sequence, ctx.args)
        yaml_paths.append(yaml_path)

    shards_dir = ctx.out_dir / "boltz_shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    extra = _boltz_extra_cli_args(ctx.args)

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(yaml_paths), ctx.args.shard_size):
        shard_idx = i // ctx.args.shard_size
        shard = shards_dir / f"shard_{shard_idx}"
        shard.mkdir(parents=True, exist_ok=True)
        for yaml_path in yaml_paths[i : i + ctx.args.shard_size]:
            copy2(yaml_path, shard / yaml_path.name)
        manifest_rows.append((str(shard), extra))

    return manifest_rows
