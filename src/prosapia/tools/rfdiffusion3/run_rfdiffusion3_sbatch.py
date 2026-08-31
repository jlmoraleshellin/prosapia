#!/usr/bin/env python3
"""
Submit a SLURM array job to run RFdiffusion3 (foundry) symmetric motif scaffolding.

This tool does one thing: for each parent symmetric design, prepend N newly-designed
residues to the N-terminus of every chain and re-diffuse under the assembly's symmetry.

RFD3 is file-driven (like AF3): one inputs JSON holds many designs as a
``{design_name: InputSpecification}`` dict, and ``rfd3 design`` is pointed at it.
RFD3's symmetric sampler takes a contig describing a **single asymmetric unit** and
replicates it, so the per-design spec is just:

    {
      "input": "/abs/path/<...>_INPUT.pdb",
      "contig": "20,A1-131",                # 20 designed res + chain-A motif 1..131
      "length": 151,                         # prepend + motif length
      "symmetry": {"id": "C11", "is_symmetric_motif": true}
    }

run with ``inference_sampler.kind=symmetry``. The contig range and the symmetry order
are derived automatically by reading the input PDB (chain-A residue range, polymer chain
count); the user only supplies the prepend length.

Usage:
    sapia run rfdiffusion3 outputs/RUN -d db1 --prepend-length 20
    sapia run rfdiffusion3 outputs/RUN -d db1 --symmetry D4 --num-designs 4
"""

import json
import os
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, cast

import gemmi
from dotenv import load_dotenv

from prosapia.core import CommonArgs, ManifestCtx

load_dotenv()

RFD3_CKPT = os.getenv("RFD3_CKPT", "")


class RFD3Args(CommonArgs):
    prepend_length: int
    num_designs: int
    num_timesteps: int
    step_scale: float
    symmetry: str
    asym_chain: str
    ckpt_path: str
    low_memory: bool
    shard_size: int
    set: list[str]


def _add_rfd3_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--prepend-length",
        type=int,
        default=20,
        help="Newly-designed residues added at each chain's N-terminus. Defaults to 20.",
    )
    parser.add_argument(
        "--num-designs",
        type=int,
        default=1,
        help="Designs generated per parent (-> diffusion_batch_size). Defaults to 1.",
    )
    parser.add_argument(
        "--symmetry",
        type=str,
        default="auto",
        help="Symmetry group id. 'auto' (default) derives cyclic C<n_chains> from the "
        "input PDB; any other value (e.g. C11, D4) is used verbatim as symmetry.id.",
    )
    parser.add_argument(
        "--asym-chain",
        type=str,
        default="A",
        help="Chain treated as the asymmetric unit for the contig. Defaults to 'A'.",
    )
    parser.add_argument(
        "--num-timesteps",
        type=int,
        default=200,
        help="Diffusion denoising timesteps (-> inference_sampler.num_timesteps). "
        "Defaults to 200.",
    )
    parser.add_argument(
        "--step-scale",
        type=float,
        default=1.5,
        help="Diffusion step size scale; higher -> less diverse, more designable "
        "(-> inference_sampler.step_scale). Defaults to 1.5.",
    )
    parser.add_argument(
        "--ckpt-path",
        type=str,
        default=RFD3_CKPT,
        help="RFD3 checkpoint path (-> ckpt_path). Defaults to $RFD3_CKPT, else "
        "rfd3's own default (auto-discovered via foundry install).",
    )
    parser.add_argument(
        "--low-memory",
        action="store_true",
        help="Enable rfd3 low_memory_mode for tight GPU RAM.",
    )
    parser.add_argument(
        "--shard-size",
        type=int,
        default=10,
        help="Number of design keys per shard JSON / array task. Defaults to 10.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra rfd3 Hydra override, appended verbatim. Repeatable. "
        "Escape hatch for options without a dedicated flag.",
    )


def _chain_geometry(pdb_path: Path, chain_id: str) -> tuple[int, int, int]:
    """Return (first_res, last_res, n_polymer_chains) for the asymmetric-unit chain.

    Reads the first model of the input PDB. ``first_res``/``last_res`` are the residue
    seqid numbers bounding ``chain_id``'s polymer; ``n_polymer_chains`` counts polymer
    chains in the model (the cyclic symmetry order when symmetry is 'auto').
    """
    structure = gemmi.read_structure(str(pdb_path))
    model = structure[0]

    n_chains = 0
    geometry: tuple[int, int] | None = None
    for chain in model:
        polymer = chain.get_polymer()
        if len(polymer) == 0:
            continue
        n_chains += 1
        if chain.name == chain_id:
            nums = [res.seqid.num for res in polymer]
            geometry = (min(nums), max(nums))  # type: ignore

    if geometry is None:
        raise ValueError(f"{pdb_path}: no polymer chain named '{chain_id}'")

    return geometry[0], geometry[1], n_chains


def _build_spec(input_path: Path, args: RFD3Args) -> dict[str, Any]:
    first, last, n_chains = _chain_geometry(input_path, args.asym_chain)
    motif_len = last - first + 1
    sym_id = f"C{n_chains}" if args.symmetry == "auto" else args.symmetry
    return {
        "input": str(input_path),
        "contig": f"{args.prepend_length},{args.asym_chain}{first}-{last}",
        "length": args.prepend_length + motif_len,
        "symmetry": {"id": sym_id, "is_symmetric_motif": True},
    }


def _cli_overrides(args: RFD3Args) -> str:
    """Assemble the run-wide rfd3 Hydra overrides string (same for every shard)."""
    overrides = [
        f"diffusion_batch_size={args.num_designs}",
        f"inference_sampler.num_timesteps={args.num_timesteps}",
        f"inference_sampler.step_scale={args.step_scale}",
        "inference_sampler.kind=symmetry",
    ]
    if args.low_memory:
        overrides.append("low_memory_mode=True")
    if args.ckpt_path:
        overrides.append(f"ckpt_path={args.ckpt_path}")
    overrides.extend(args.set)
    return " ".join(overrides)


def build_rfd3_manifest(ctx: ManifestCtx[RFD3Args]) -> list[tuple[str, ...]]:
    ready = ctx.ready

    specs: list[tuple[str, dict[str, Any]]] = []
    for name in ready.index:
        name = cast(str, name)
        input_path = Path(str(ready.at[name, ctx.args.input_column])).resolve()
        if not input_path.exists():
            print(f"{name}: MISSING {input_path} (skipping)")
            continue
        specs.append((name, _build_spec(input_path, ctx.args)))

    if not specs:
        return []

    shards_dir = ctx.out_dir / "rfd3_inputs"
    shards_dir.mkdir(parents=True, exist_ok=True)

    overrides = _cli_overrides(ctx.args)
    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(specs), ctx.args.shard_size):
        shard_idx = i // ctx.args.shard_size
        chunk = dict(specs[i : i + ctx.args.shard_size])
        shard_json = shards_dir / f"shard_{shard_idx}.json"
        shard_json.write_text(json.dumps(chunk, indent=2))
        manifest_rows.append((str(shard_json), overrides))

    return manifest_rows
