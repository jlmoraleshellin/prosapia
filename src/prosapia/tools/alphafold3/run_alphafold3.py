#!/usr/bin/env python3
"""
Run AlphaFold3 predictions on the sequences in a table.

Creates individual AF3 JSON input files, groups them into shard directories, and
submits one task per shard (each task runs AF3 on a whole shard via ``--input_dir``).

Chains are derived per-sequence from the MPNN chainbreak syntax (``/``-separated
chains): chains sharing a sequence collapse into one homo-oligomer entity, distinct
sequences become separate hetero-oligomer entities. ``--chains`` narrows which
chains to predict (mini-language, e.g. ``A:D``).

MSAs and templates: by default AF3 searches every chain, which needs the genetic
databases. These flags decide per chain instead (letters are positional in the
chainbreak sequence, first segment is A; chains no flag names are still searched):

- ``--no-msa``: every chain gets an empty MSA and no templates.
- ``--msa-empty-chains B``: the named chains do.
- ``--msa-file A=a.a3m``: the named chains read that A3M, copied into the run.
  ``--paired-msa-file`` adds a paired A3M for chains that already have one.
- ``--templates-json file.json``: ``{"A": [<AF3 template entry>, ...]}``; each
  ``mmcifPath`` is copied into the run. Chains named there need an MSA policy too.

AF3 rejects a chain whose unpaired MSA, paired MSA and templates are only partly set,
so every policy written here sets all three. Chains sharing a sequence are one AF3
entity and must get the same policy: name them together (``--msa-file A:C=t.a3m``).

Manifest layout: the shard directory plus an ``extra`` field holding the
``run_alphafold.py`` data-pipeline option: ``--norun_data_pipeline`` when every chain
in the shard has a policy, else ``--run_data_pipeline``. AF3 checks that the databases
exist whenever the pipeline is on, so a database-free run needs the former.

Usage:
    sapia run alphafold3 outputs/20260420_123035_grow_hairpin --table table1
    sapia run alphafold3 <run_dir> -t table1 --msa-file A:C=/runs/htnf.a3m --msa-empty-chains D
"""

import json
import string
from argparse import ArgumentParser
from pathlib import Path
from shutil import copy2, rmtree
from typing import cast

from prosapia.core import CommonArgs, ManifestCtx
from prosapia.core.executors import volume_path
from prosapia.utils import (
    add_chains_and_positions_args,
    build_chain_map,
    expand_chain_spec,
    group_by_sequence,
)

AF3_NAME_CHARS = frozenset(string.ascii_letters + string.digits + "_-.")


class AlphaFold3Args(CommonArgs):
    shard_size: int
    model_seeds: list[int]
    chains: str | None
    positions: str | None
    no_msa: bool
    msa_empty_chains: str | None
    msa_file: list[str] | None
    paired_msa_file: list[str] | None
    templates_json: str | None


def af3_sanitised_name(name: str) -> str:
    """The directory AF3 writes this design to (``Input.sanitised_name``)."""
    return "".join(c for c in name.replace(" ", "_") if c in AF3_NAME_CHARS)


def empty_policy() -> dict:
    """Search nothing. ``templates`` must be set, even to ``[]``, or AF3 crashes."""
    return {"unpairedMsa": "", "pairedMsa": "", "templates": []}


def stage(src: Path, dest_dir: Path, tag: str) -> str:
    """Copy ``src`` into the run and return its path as the task container sees it."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{tag}_{src.name}"
    copy2(src, dest)
    return str(volume_path(dest))


def parse_chains_path(spec: str, flag: str) -> tuple[list[str], Path]:
    """``CHAINS=PATH`` -> chain letters and the file."""
    chains, sep, path = spec.partition("=")
    letters = expand_chain_spec(chains) if sep else []
    if not letters or not path:
        raise ValueError(f"{flag} {spec!r} must be CHAINS=PATH, e.g. {flag} A:C=t.a3m")
    src = Path(path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"{flag} {spec!r}: no file at {src}")
    return letters, src


def assign(
    policies: dict[str, dict], letters: list[str], policy: dict, flag: str
) -> None:
    taken = [c for c in letters if c in policies]
    if taken:
        raise ValueError(
            f"{flag}: chain(s) {','.join(taken)} already have an MSA policy. "
            "A chain takes exactly one."
        )
    policies.update({c: dict(policy) for c in letters})


def stage_template(entry: dict, base: Path, dest_dir: Path, tag: str) -> dict:
    """Point a template entry's ``mmcifPath`` at a copy inside the run."""
    if "mmcifPath" not in entry:
        return entry
    src = Path(entry["mmcifPath"]).expanduser()
    if not src.is_absolute():
        src = base / src
    return {**entry, "mmcifPath": stage(src, dest_dir, tag)}


def resolve_chain_policies(args: AlphaFold3Args, out_dir: Path) -> dict[str, dict]:
    """Turn the MSA/template flags into ``{chain: AF3 json fields}``.

    Chains with no entry are left for AF3 to search.
    """
    if args.no_msa and (
        args.msa_empty_chains is not None
        or args.msa_file
        or args.paired_msa_file
        or args.templates_json
    ):
        raise ValueError(
            "--no-msa empties every chain, so it cannot be combined with "
            "--msa-empty-chains / --msa-file / --paired-msa-file / --templates-json."
        )

    policies: dict[str, dict] = {}

    if args.msa_empty_chains is not None:
        letters = expand_chain_spec(args.msa_empty_chains)
        if not letters:
            raise ValueError(
                f"--msa-empty-chains {args.msa_empty_chains!r} expands to no chains. "
                "Give at least one chain letter (e.g. 'B', 'A,C', 'B:D'), or omit "
                "the flag."
            )
        assign(policies, letters, empty_policy(), "--msa-empty-chains")

    for spec in args.msa_file or []:
        letters, src = parse_chains_path(spec, "--msa-file")
        path = stage(src, out_dir / "af3_msas", "".join(letters))
        policy = {"unpairedMsaPath": path, "pairedMsa": "", "templates": []}
        assign(policies, letters, policy, "--msa-file")

    for spec in args.paired_msa_file or []:
        letters, src = parse_chains_path(spec, "--paired-msa-file")
        unpaired = [c for c in letters if "unpairedMsaPath" not in policies.get(c, {})]
        if unpaired:
            raise ValueError(
                f"--paired-msa-file names chain(s) {','.join(unpaired)} without an "
                "--msa-file for them. AF3 needs both alignments set together."
            )
        path = stage(src, out_dir / "af3_paired_msas", "".join(letters))
        for c in letters:
            policies[c].pop("pairedMsa", None)
            policies[c]["pairedMsaPath"] = path

    if args.templates_json:
        templates_path = Path(args.templates_json).expanduser()
        for key, entries in json.loads(templates_path.read_text()).items():
            letters = expand_chain_spec(key)
            unset = [c for c in letters if c not in policies]
            if unset:
                raise ValueError(
                    f"--templates-json names chain(s) {','.join(unset)} without an "
                    "MSA policy. AF3 rejects partly specified chains: also give "
                    "them --msa-file or --msa-empty-chains."
                )
            tag = "".join(letters)
            staged = [
                stage_template(e, templates_path.parent, out_dir / "af3_templates", tag)
                for e in entries
            ]
            for c in letters:
                policies[c]["templates"] = staged

    return policies


def write_af3_json(
    json_path: Path,
    name: str,
    chain_map: dict[str, str],
    model_seeds: list[int],
    *,
    no_msa: bool = False,
    policies: dict[str, dict] | None = None,
    version: int = 1,
) -> bool:
    """Write one AF3 JSON input; return whether every entity has an MSA policy.

    Chains sharing a sequence collapse into one protein entity with a multi-letter
    ``id`` (homo-oligomer); distinct sequences become separate entities
    (hetero-oligomer). A policy is per entity, so naming only some of the chains
    that share a sequence is an error.
    """
    policies = policies or {}
    default = empty_policy() if no_msa else {}

    unknown = [c for c in policies if c not in chain_map]
    if unknown:
        raise ValueError(
            f"design {name!r}: the MSA/template flags name chain(s) "
            f"{','.join(unknown)}, which this complex does not have. Chains present "
            f"after --chains: {','.join(chain_map) or '(none)'}. Chain letters are "
            "positional in the '/'-chainbreak sequence (first segment is A)."
        )

    sequences: list[dict] = []
    specified = True
    for letters, seq in group_by_sequence(chain_map):
        chosen = [policies.get(c) or default for c in letters]
        if any(p != chosen[0] for p in chosen):
            raise ValueError(
                f"design {name!r}: chains {','.join(letters)} share one sequence and "
                "therefore form a SINGLE AlphaFold3 entity, which can only have one "
                "MSA/template policy. Give them the same one (e.g. --msa-file "
                f"{','.join(letters)}=<a3m>) or name none of them."
            )
        specified &= bool(chosen[0])
        sequences.append({"protein": {"id": letters, "sequence": seq, **chosen[0]}})

    payload = {
        "name": name,
        "modelSeeds": model_seeds,
        "sequences": sequences,
        "dialect": "alphafold3",
        "version": version,
    }
    json_path.write_text(json.dumps(payload, indent=2))
    return specified


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
        help="Give EVERY chain an empty MSA and no templates, so nothing is "
        "searched. Cannot be combined with the per-chain MSA flags.",
    )
    parser.add_argument(
        "--msa-empty-chains",
        type=str,
        default=None,
        metavar="B",
        help="Chains given an empty MSA and no templates, in the chain mini-language "
        "(':' inclusive letter range, ',' separates): e.g. 'B', 'A,C', 'B:D'. For a "
        "de-novo binder complex name the BINDER chain; the rest are still searched. "
        "Chains sharing a sequence must be named together. Default: unset.",
    )
    parser.add_argument(
        "--msa-file",
        action="append",
        default=None,
        metavar="CHAINS=PATH",
        help="An A3M alignment for the named chains (chain mini-language, e.g. "
        "A=t.a3m or A:C=t.a3m), repeatable. Chains sharing a sequence must be named "
        "together. The file is copied into the run; its first sequence must be the "
        "chain's own. Default: unset.",
    )
    parser.add_argument(
        "--paired-msa-file",
        action="append",
        default=None,
        metavar="CHAINS=PATH",
        help="A paired A3M for chains that already have an --msa-file, repeatable. "
        "Default: unset, i.e. no paired alignment.",
    )
    parser.add_argument(
        "--templates-json",
        type=str,
        default=None,
        metavar="FILE",
        help='JSON mapping chains to AF3 template entries: {"A:C": [{"mmcifPath": '
        '"ref.cif", "queryIndices": [...], "templateIndices": [...]}]}. Keys use the '
        "chain mini-language. Relative mmcifPath entries resolve against the file and "
        "are copied into the run. Every chain named also needs an --msa-file or "
        "--msa-empty-chains. Default: unset.",
    )


def build_af3_manifest(ctx: ManifestCtx[AlphaFold3Args]):
    args = ctx.args
    json_dir = ctx.submission_dir / "af3_inputs"
    json_dir.mkdir(parents=True, exist_ok=True)

    policies = resolve_chain_policies(args, ctx.submission_dir)
    version = 2 if args.msa_file or args.paired_msa_file or args.templates_json else 1

    json_paths: list[Path] = []
    specified: dict[Path, bool] = {}
    for name in ctx.ready.index:
        name = cast(str, name)
        sequence = str(ctx.ready.at[name, args.input_column])
        chain_map = build_chain_map(
            sequence, args.chains, args.positions, ctx.lookup, name
        )
        json_path = json_dir / f"{name}.json"
        specified[json_path] = write_af3_json(
            json_path,
            name,
            chain_map,
            args.model_seeds,
            no_msa=args.no_msa,
            policies=policies,
            version=version,
        )
        json_paths.append(json_path)

    ctx.write_meta(
        no_msa=bool(args.no_msa),
        msa_empty_chains=args.msa_empty_chains,
        msa_file=list(args.msa_file or []),
        paired_msa_file=list(args.paired_msa_file or []),
        templates_json=args.templates_json,
    )

    shards_dir = ctx.submission_dir / "af3_shards"
    rmtree(shards_dir, ignore_errors=True)
    shards_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(json_paths), args.shard_size):
        shard_idx = i // args.shard_size
        shard = shards_dir / f"shard_{shard_idx}"
        shard.mkdir(parents=True, exist_ok=True)
        batch = json_paths[i : i + args.shard_size]
        for json_path in batch:
            copy2(json_path, shard / json_path.name)
        extra = (
            "--norun_data_pipeline"
            if all(specified[p] for p in batch)
            else "--run_data_pipeline"
        )
        manifest_rows.append((str(shard), extra))

    return manifest_rows
