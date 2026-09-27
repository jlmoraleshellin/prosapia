"""Shared building blocks for the structure-prediction tools.

The predictors (alphafold3, boltz, colabfold, openfold3) all take a proteinmpnn
``/``-chainbreak sequence, narrow it to a set of chains, optionally slice each
chain down to a subset of residues, and run one GPU array. This module holds the
parts they would otherwise copy-paste: the ``--chains`` / ``--positions`` / ``--devices``
argparse blocks, the ``devices -> gpus_per_task`` convenience, and the chain-map
builder that turns a raw sequence into the ``{chain: sequence}`` fed to each
predictor's input writer.
"""

from argparse import ArgumentParser

from ..core.data_manager import LookupFn
from .chains import select_chains
from .expr import resolve_template
from .positions import parse_chain_positions


def add_chains_and_positions_args(parser: ArgumentParser) -> None:
    """Add the shared ``--chains`` chain selector and ``--positions`` residue selector"""
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
        "--positions",
        type=str,
        default=None,
        metavar="10:50/1:30",
        help="Residues to predict, in the position "
        "mini-language: '/' maps groups one-to-one onto the selected chains (a "
        "single group broadcasts to all), ',' separates fragments, 'start:end' is "
        "inclusive and 1-indexed within each chain, open ends are allowed "
        "('10:' -> to the C-terminus, ':50' -> from the N-terminus, ':' -> whole "
        "chain), and '{...}' islands resolve table columns up the lineage (e.g. "
        "'{prebundle_length+1}:' trims a prefix). Non-contiguous fragments are "
        "concatenated. Default: predict the full sequence.",
    )


def add_devices_arg(parser: ArgumentParser) -> None:
    """Add the shared ``--devices`` GPU-count arg."""
    parser.add_argument(
        "--devices",
        type=int,
        default=1,
        help="Number of GPUs per task. "
        "Automatically sets --gpus-per-task to match unless explicitly overridden. "
        "Defaults to 1.",
    )


def maybe_set_gpus_per_task(args) -> None:
    """Mirror ``--devices`` onto ``--gpus-per-task`` when more than one GPU."""
    if args.devices > 1:
        args.gpus_per_task = args.devices


def build_chain_map(
    sequence: str,
    chains_spec: str | None,
    positions_spec: str | None,
    lookup: LookupFn,
    name: str,
) -> dict[str, str]:
    """Select chains from ``sequence`` and, if given, slice each to kept residues.

    ``chains_spec`` narrows which chains to predict (see ``select_chains``).
    ``positions_spec`` (position mini-language) lists the residues to KEEP: ``/``
    maps groups onto the selected chains in order -- one group broadcasts to every
    chain, several map one-to-one (their count must equal the chain count).
    Positions are 1-indexed within each chain and kept fragments are concatenated.
    An empty spec (or ``'none'``) returns the selected chains untouched.
    """
    chain_map = select_chains(sequence, chains_spec)
    if not positions_spec or positions_spec.strip().lower() == "none":
        return chain_map

    resolved = (
        resolve_template(positions_spec, lookup, name).strip().strip("[]").strip()
    )
    if not resolved:
        return chain_map

    group_specs = resolved.split("/")
    letters = list(chain_map)
    if len(group_specs) == 1:
        group_specs = group_specs * len(letters)
    elif len(group_specs) != len(letters):
        raise ValueError(
            f"design {name!r}: --positions has {len(group_specs)} chain groups but "
            f"{len(letters)} chains are selected (use '/' per chain, or one group "
            f"to apply to all)"
        )

    kept: dict[str, str] = {}
    for letter, group in zip(letters, group_specs):
        seq = chain_map[letter]
        positions = parse_chain_positions(group, length=len(seq), name=name)
        kept[letter] = "".join(seq[p - 1] for p in positions)
    return kept
