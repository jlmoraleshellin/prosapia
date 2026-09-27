#!/usr/bin/env python3
"""
Submit a SLURM array job to run boltz predictions on MPNN-designed sequences.

Reads sequences from an MPNN table, writes one boltz YAML input per sequence,
groups them into shard directories, and submits a sbatch array where each task
runs boltz on a whole shard (optionally on multiple GPUs via --devices).

Chains are derived per-sequence from the MPNN chainbreak syntax (``/``-separated
chains): chains sharing a sequence collapse into one homo-oligomer entity, distinct
sequences become separate hetero-oligomer entities. ``--chains`` narrows which
chains to predict (mini-language, e.g. ``A:D``). Templates are opt-in via
``--template-yaml``: the file's contents are a boltz ``templates:`` block spliced
verbatim into every generated input YAML (omit the flag for no template).

Manifest layout: the only genuinely per-task field is the shard directory. Every
run-wide boltz CLI option (``--devices``, ``--use_msa_server``, ...) is collapsed
into a single space-separated ``extra`` field (see ``_boltz_predict_global_args``), which the
sbatch drops unquoted into the ``boltz predict`` argv. Adding a run-wide flag
means extending ``_boltz_predict_global_args``, not adding a manifest column.

Usage:
    sapia run boltz outputs/20260420_123035_grow_hairpin --table table1
    sapia run boltz outputs/20260420_123035_grow_hairpin --table table1 --shard-size 20 --devices 4
"""

from argparse import ArgumentParser
from pathlib import Path
from shutil import copy2
from typing import cast

from prosapia.core import CommonArgs, ManifestCtx
from prosapia.utils import (
    add_chains_and_positions_args,
    add_devices_arg,
    build_chain_map,
    group_by_sequence,
    maybe_set_gpus_per_task,
)


class BoltzArgs(CommonArgs):
    shard_size: int
    devices: int
    use_msa_server: bool
    template_yaml: str | None
    chains: str | None
    positions: str | None


def write_boltz_yaml(
    yaml_path: Path,
    chain_map: dict[str, str],
    args: BoltzArgs,
) -> None:
    """Write a single boltz input YAML.

    ``chain_map`` is the ordered ``{chain: sequence}`` to predict. Chains sharing a
    sequence collapse into one entity with a multi-letter ``id`` (homo-oligomer);
    distinct sequences become separate ``- protein:`` entities (hetero-oligomer).

    ``template_block`` is a boltz ``templates:`` block spliced verbatim after the
    ``sequences:`` entities (empty string for no template).
    """

    def load_template_block(template_yaml: str | None) -> str:
        """Read the ``templates:`` block to splice into each input YAML."""
        if not template_yaml:
            return ""
        path = Path(template_yaml)
        if not path.is_file():
            raise FileNotFoundError(f"--template-yaml file not found: {template_yaml}")
        return path.read_text().rstrip("\n") + "\n"

    entities = [
        "  - protein:\n"
        f"      id: [{', '.join(letters)}]\n"
        f"      sequence: {seq}\n"
        + ("" if args.use_msa_server else "      msa: empty\n")
        for letters, seq in group_by_sequence(chain_map)
    ]

    yaml_text = (
        "version: 1\nsequences:\n"
        + "".join(entities)
        + load_template_block(args.template_yaml)
    )
    yaml_path.write_text(yaml_text)


def _boltz_predict_global_args(args: BoltzArgs) -> str:
    """Run-wide `boltz predict` args (same for every shard), joined space-separated."""
    parts = [f"--devices {args.devices}"]
    if args.use_msa_server:
        parts.append("--use_msa_server")
    return " ".join(parts)


def add_run_boltz_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--shard-size",
        type=int,
        default=10,
        help="Number of YAML inputs per shard directory. Defaults to 10.",
    )
    add_devices_arg(parser)
    parser.add_argument(
        "--use-msa-server",
        action="store_true",
        help="Use MSA information in the boltz input YAML.",
    )
    add_chains_and_positions_args(parser)
    parser.add_argument(
        "--template-yaml",
        type=str,
        default=None,
        help="Path to a file whose contents are a boltz `templates:` block, "
        "spliced verbatim into every generated input YAML. Omit for no template.",
    )


def build_boltz_manifest(ctx: ManifestCtx[BoltzArgs]):
    maybe_set_gpus_per_task(ctx.args)

    yaml_dir = ctx.out_dir / "boltz_inputs"
    yaml_dir.mkdir(parents=True, exist_ok=True)

    yaml_paths: list[Path] = []
    for name in ctx.ready.index:
        name = cast(str, name)
        sequence = str(ctx.ready.at[name, ctx.args.input_column])
        chain_map = build_chain_map(
            sequence, ctx.args.chains, ctx.args.positions, ctx.lookup, name
        )
        yaml_path = yaml_dir / f"{name}.yml"
        write_boltz_yaml(yaml_path, chain_map, ctx.args)
        yaml_paths.append(yaml_path)

    shards_dir = ctx.out_dir / "boltz_shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    extra = _boltz_predict_global_args(ctx.args)

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(yaml_paths), ctx.args.shard_size):
        shard_idx = i // ctx.args.shard_size
        shard = shards_dir / f"shard_{shard_idx}"
        shard.mkdir(parents=True, exist_ok=True)
        for yaml_path in yaml_paths[i : i + ctx.args.shard_size]:
            copy2(yaml_path, shard / yaml_path.name)
        manifest_rows.append((str(shard), extra))

    return manifest_rows
