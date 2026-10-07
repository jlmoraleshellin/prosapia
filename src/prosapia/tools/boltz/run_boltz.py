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

MSAs: ``--use-msa-server`` searches every chain; without it every entity is
``msa: empty``. ``--msa-empty-chains`` (requires ``--use-msa-server``) pins the named
chains to ``msa: empty`` so the rest are still searched, e.g. the natural target gets
an MSA while a de-novo binder does not. The YAMLs in ``boltz_inputs/`` are the audit
trail of what each chain was given; the policy is also recorded in ``.meta.json``.

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
    expand_chain_spec,
    group_by_sequence,
    maybe_set_gpus_per_task,
)


MSA_EMPTY_LINE = "      msa: empty\n"


class BoltzArgs(CommonArgs):
    shard_size: int
    devices: int
    use_msa_server: bool
    msa_empty_chains: str | None
    template_yaml: str | None
    chains: str | None
    positions: str | None


def resolve_msa_empty_chains(
    args: BoltzArgs,
    chain_map: dict[str, str],
    name: str,
) -> set[str] | None:
    """The chain letters pinned to ``msa: empty``, or ``None`` for the run-wide policy.

    ``None`` means ``--msa-empty-chains`` was not given: every entity is empty unless
    ``--use-msa-server``. Anything the flag asks for that cannot be honoured raises
    here, at submit time.
    """
    spec = args.msa_empty_chains
    if spec is None:
        return None

    if not args.use_msa_server:
        raise ValueError(
            "--msa-empty-chains requires --use-msa-server: without it NO entity is "
            "given an MSA, so naming a subset cannot be honoured. Either add "
            "--use-msa-server (the named chains stay empty, every other chain is "
            "searched) or drop --msa-empty-chains (nothing is searched)."
        )

    letters = expand_chain_spec(spec)
    if not letters:
        raise ValueError(
            f"--msa-empty-chains {spec!r} expands to no chains. Give at least one "
            "chain letter (e.g. 'B', 'A,C', 'B:D'), or omit the flag."
        )

    missing = [c for c in letters if c not in chain_map]
    if missing:
        present = ",".join(chain_map) or "(none)"
        raise ValueError(
            f"design {name!r}: --msa-empty-chains names chain(s) "
            f"{','.join(missing)}, which this complex does not have. Chains "
            f"present after --chains: {present}. Chain letters are positional in "
            "the '/'-chainbreak sequence (first segment is A)."
        )
    return set(letters)


def write_boltz_yaml(
    yaml_path: Path,
    chain_map: dict[str, str],
    args: BoltzArgs,
    name: str = "",
) -> None:
    """Write a single boltz input YAML.

    ``chain_map`` is the ordered ``{chain: sequence}`` to predict. Chains sharing a
    sequence collapse into one entity with a multi-letter ``id`` (homo-oligomer);
    distinct sequences become separate ``- protein:`` entities (hetero-oligomer).

    ``msa: empty`` is decided per entity: from ``--msa-empty-chains`` when given,
    else from the run-wide ``--use-msa-server``. An entity has a single MSA policy,
    so naming only some of the chains that share a sequence is an error.

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

    msa_empty = resolve_msa_empty_chains(args, chain_map, name)

    entities: list[str] = []
    for letters, seq in group_by_sequence(chain_map):
        if msa_empty is None:
            msa_line = "" if args.use_msa_server else MSA_EMPTY_LINE
        else:
            named = [c for c in letters if c in msa_empty]
            if named and len(named) != len(letters):
                unnamed = [c for c in letters if c not in msa_empty]
                raise ValueError(
                    f"design {name!r}: chains {','.join(letters)} share one sequence "
                    "and therefore form a SINGLE boltz entity, which can only have "
                    f"one MSA policy. --msa-empty-chains names {','.join(named)} but "
                    f"not {','.join(unnamed)}. Name all of them or none."
                )
            msa_line = MSA_EMPTY_LINE if named else ""
        entities.append(
            "  - protein:\n"
            f"      id: [{', '.join(letters)}]\n"
            f"      sequence: {seq}\n" + msa_line
        )

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
    parser.add_argument(
        "--msa-empty-chains",
        type=str,
        default=None,
        metavar="B",
        help="Chains pinned to `msa: empty` even when --use-msa-server is on, in the "
        "chain mini-language (':' inclusive letter range, ',' separates): e.g. 'B', "
        "'A,C', 'B:D'. For a de-novo binder complex name the BINDER chain, so the "
        "natural target is searched and the design is not. Requires "
        "--use-msa-server; a chain the complex does not have is an error. "
        "Default: unset, i.e. the run-wide policy (every chain empty unless "
        "--use-msa-server, every chain searched with it).",
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
        write_boltz_yaml(yaml_path, chain_map, ctx.args, name)
        yaml_paths.append(yaml_path)

    ctx.write_meta(
        use_msa_server=bool(ctx.args.use_msa_server),
        msa_empty_chains=ctx.args.msa_empty_chains,
    )

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
