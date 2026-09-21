#!/usr/bin/env python3
"""
Submit a SLURM array job to run RFdiffusion3 (foundry).

RFD3 is file-driven (like AF3): one inputs JSON holds many designs as a
``{design_name: InputSpecification}`` dict, and one ``rfd3 design`` process is
pointed at it and iterates those keys **in series** internally. So a design group
is one JSON key; ``--shard-size`` packs N keys into a shard JSON, and one array
task runs the whole shard on its single GPU (series, memory-safe -- there is no
concurrent-process fan-out like rfdiffusion's ``--per-card``).

The tool injects only the per-design ``InputSpecification`` (``contig``, ``input``,
``length``, ``symmetry``, ``partial_t``) and defers everything else to rfd3's own
config plus whatever ``inference_sampler.*`` / ``--set`` overrides the user supplies.

Contigs are authored in RFD3's native contig syntax, with ``{expr}`` placeholders
resolved per-design against the table lineage (integers, bare column names, and
+ - * // arithmetic; see resolve_expr):

    --contigs 'A1-{motif_end},30'      # motif A1..motif_end + 30 designed residues
    --contigs '20,A1-131'              # 20 designed residues + chain-A motif

Symmetry is the model's job, not the contig's: with ``--symmetry`` set, rfd3's
symmetric sampler (``symmetry`` spec field + ``inference_sampler.kind=symmetry``)
replicates a **single asymmetric-unit** contig across the group -- you write one
unit, never all chains, and there is no per-chain replication flag. ``--symmetry
auto`` derives ``C<n_chains>`` from the input's polymer chain count. A de-novo
symmetric oligomer needs no contig at all -- just one subunit's ``--length`` and
``--symmetry`` (e.g. ``--length 100 --symmetry C5``).

Extra ``InputSpecification`` fields the dedicated flags don't expose (``ligand``,
``select_fixed_atoms``, ``select_hotspots``, ...) can be supplied via ``--extra-spec``,
a YAML or JSON file whose top-level mapping is merged into every design's spec; its
string values may embed the same ``{expr}`` placeholders. Setting a field that a
dedicated flag also sets is an error. Each design needs a ``contig`` or a ``length``
(from a flag or --extra-spec).

Usage:
    # general, table-driven
    sapia run rfdiffusion3 outputs/RUN --table table1 \\
        --contigs 'A1-{motif_end},30' --length '80-150'

    # symmetric motif scaffold: single-unit contig, sampler builds the C11 assembly
    sapia run rfdiffusion3 outputs/RUN --table table1 \\
        --contigs '20,A1-131' --symmetry auto --num-designs 4

    # root run: motif/partial diffusion of one PDB not yet in any table
    sapia run rfdiffusion3 outputs/RUN \\
        --input-pdb motif.pdb --contigs '20,A1-131' --symmetry C11
"""

import json
import os
import re
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, cast

import gemmi
import yaml
from dotenv import load_dotenv

from prosapia.core import CommonArgs, ManifestCtx
from prosapia.core.data_manager import LookupFn
from prosapia.utils import resolve_template

load_dotenv()

RFD3_CKPT = os.getenv("RFD3_CKPT", "")

# A {expr} placeholder island in a contig/length template, resolved per-design up
# the table lineage. Meaningless in a root run (no table), so we reject it there.
_HAS_PLACEHOLDER = re.compile(r"\{[^}]*\}")


class SpecConfigError(ValueError):
    """A run-wide spec misconfiguration that applies to every design (e.g. an
    --extra-spec field colliding with a dedicated flag, or no contig from either
    source). Unlike a per-row error, it is not swallowed by the create loop's
    warn-and-skip -- it fails the whole submit up front."""


class RFD3Args(CommonArgs):
    contigs: str | None
    length: str | None
    extra_spec: str | None
    input_pdb: Path | None
    symmetry: str | None
    num_designs: int
    num_timesteps: int
    step_scale: float
    partial_t: float | None
    ckpt_path: str
    low_memory: bool
    shard_size: int
    set: list[str]


def add_run_rfd3_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--contigs",
        type=str,
        default=None,
        help="RFD3 contig template (per-design `contig`). For a symmetric design, "
        "write the contig for a SINGLE asymmetric unit -- rfd3's symmetric sampler "
        "replicates it across the group (see --symmetry). Indexed motif segments "
        "reference the input by chain+residue (e.g. `A40-60`), designed regions are "
        "bare numbers or ranges (e.g. `30` or `60-80`), and `/0` breaks chains. May "
        "embed {expr} placeholders resolved per-design up the lineage (integers, bare "
        "table column names, and + - * //). Optional: a design needs a `contig` or a "
        "`--length`; the `contig` may instead come from --extra-spec.",
    )
    parser.add_argument(
        "--length",
        type=str,
        default=None,
        help="Total design length constraint (per-design `length`): an int or "
        "'min-max'. May embed {expr} placeholders. For a de-novo symmetric oligomer "
        "this is one subunit's length (e.g. --length 100 --symmetry C5, no contig). "
        "Omitted by default (rfd3 infers it from the contig).",
    )
    parser.add_argument(
        "--extra-spec",
        type=str,
        default=None,
        help="Path to a YAML or JSON file: a mapping of extra rfd3 "
        "InputSpecification fields (e.g. ligand, select_fixed_atoms, "
        "select_hotspots, redesign_motif_sidechains) merged into EVERY design's "
        "spec. String values may embed {expr} placeholders resolved per-design up "
        "the lineage. Setting a field that a dedicated flag also sets (contig, "
        "input, length, symmetry, partial_t) is an error.",
    )
    parser.add_argument(
        "--input-pdb",
        type=Path,
        default=None,
        help="Single input structure to diffuse when starting a ROOT run (no "
        "--table): motif/partial diffusion of one PDB that isn't in any table yet. "
        "Only valid without --table (with a table, inputs come from --input-column). "
        "Omit for pure de-novo generation. The design group is named after this "
        "file's stem.",
    )
    parser.add_argument(
        "--symmetry",
        type=str,
        default=None,
        help="Symmetry group id (per-design `symmetry.id`, also turns on "
        "inference_sampler.kind=symmetry so the sampler replicates the single "
        "asymmetric-unit contig across the group). 'auto' derives C<n_chains> from "
        "the input structure's polymer chain count; any other value is used verbatim "
        "(e.g. C11, D4). Omitted by default (no symmetry).",
    )
    parser.add_argument(
        "--num-designs",
        type=int,
        default=1,
        help="Designs generated per input key (-> diffusion_batch_size). Defaults to 1.",
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
        "--partial-t",
        type=float,
        default=None,
        help="Partial-diffusion noise in Angstroms (per-design `partial_t`, "
        "recommended 5.0-15.0). Omitted by default (full diffusion).",
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
        "Escape hatch for options without a dedicated flag (e.g. n_batches=2).",
    )


def _count_polymer_chains(pdb_path: Path) -> int:
    """Count polymer chains in the input's first model (the cyclic symmetry order
    used by ``--symmetry auto``)."""
    structure = gemmi.read_structure(str(pdb_path))
    model = structure[0]
    n_chains = sum(1 for chain in model if len(chain.get_polymer()) > 0)
    if n_chains == 0:
        raise ValueError(f"{pdb_path}: no polymer chains found")
    return n_chains


def _coerce_length(length: str) -> int | str:
    """Length is an int when purely numeric, else a verbatim 'min-max' string."""
    return int(length) if length.isdigit() else length


def load_extra_spec(extra_spec: str | None) -> dict[str, Any]:
    """Parse the --extra-spec YAML/JSON file into a mapping of extra spec fields.

    Returns ``{}`` when unset or empty. YAML is a JSON superset, so ``yaml.safe_load``
    parses both. Raises FileNotFoundError for a missing path and ValueError if the
    top level isn't a mapping.
    """
    if not extra_spec:
        return {}
    path = Path(extra_spec)
    if not path.is_file():
        raise FileNotFoundError(f"--extra-spec file not found: {extra_spec}")
    data = yaml.safe_load(path.read_text())
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"--extra-spec must be a mapping of InputSpecification fields, got "
            f"{type(data).__name__}"
        )
    return data


def _tree_has_placeholder(obj: Any) -> bool:
    """True if any string key/value anywhere in ``obj`` embeds a ``{expr}`` island.

    Only string leaves are inspected -- structural dict/list braces don't count.
    """
    if isinstance(obj, dict):
        return any(
            _tree_has_placeholder(k) or _tree_has_placeholder(v) for k, v in obj.items()
        )
    if isinstance(obj, list):
        return any(_tree_has_placeholder(v) for v in obj)
    if isinstance(obj, str):
        return bool(_HAS_PLACEHOLDER.search(obj))
    return False


def _resolve_tree(obj: Any, lookup: LookupFn, name: str) -> Any:
    """Recursively resolve ``{expr}`` placeholders in a parsed spec structure.

    Strings (and dict keys) pass through ``resolve_template``; dicts and lists are
    walked; other scalars (int/float/bool/None) are returned unchanged. So native
    YAML/JSON types are preserved except where a string embeds ``{expr}``.
    """
    if isinstance(obj, dict):
        return {
            resolve_template(str(k), lookup, name): _resolve_tree(v, lookup, name)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_resolve_tree(v, lookup, name) for v in obj]
    if isinstance(obj, str):
        return resolve_template(obj, lookup, name)
    return obj


def _build_spec(
    name: str,
    input_path: Path | None,
    args: RFD3Args,
    lookup: LookupFn,
    extra_fields: dict[str, Any],
) -> dict[str, Any]:
    """Build one design's rfd3 ``InputSpecification`` dict.

    ``input_path`` is the (absolute) motif source, or ``None`` for a de-novo design
    (the ``input`` field is then omitted). ``extra_fields`` is the parsed --extra-spec
    mapping, resolved per-design and merged in. Raises ValueError on a per-row problem
    (an unresolvable contig/length, or ``--symmetry auto`` with no input to count
    chains from), and the run-wide ``SpecConfigError`` on an extra-spec collision or
    when neither a contig nor a length is supplied by any source.
    """
    tool_fields: dict[str, Any] = {}

    if args.contigs is not None:
        tool_fields["contig"] = resolve_template(args.contigs, lookup, name)

    if args.length is not None:
        tool_fields["length"] = _coerce_length(
            resolve_template(args.length, lookup, name)
        )

    if input_path is not None:
        tool_fields["input"] = str(input_path)

    if args.symmetry is not None:
        if args.symmetry == "auto":
            if input_path is None:
                raise ValueError(
                    "--symmetry auto needs an input structure to count chains, but "
                    "this design has none. Pass an explicit symmetry (e.g. C4) or "
                    "provide --input-pdb."
                )
            sym_id = f"C{_count_polymer_chains(input_path)}"
        else:
            sym_id = args.symmetry
        # is_symmetric_motif declares that an INPUT motif is already symmetrized; it
        # only applies when there is a motif (a de-novo symmetric run omits it).
        symmetry: dict[str, Any] = {"id": sym_id}
        if input_path is not None:
            symmetry["is_symmetric_motif"] = True
        tool_fields["symmetry"] = symmetry

    if args.partial_t is not None:
        tool_fields["partial_t"] = args.partial_t

    resolved_extra = _resolve_tree(extra_fields, lookup, name)
    collisions = sorted(set(tool_fields) & set(resolved_extra))
    if collisions:
        raise SpecConfigError(
            f"field(s) {collisions} set by both a dedicated flag and --extra-spec; "
            "remove them from one source"
        )

    spec = {**resolved_extra, **tool_fields}
    # rfd3 needs something that defines what to build: a contig (motif/scaffold) or a
    # length (e.g. a de-novo symmetric oligomer's subunit length).
    if "contig" not in spec and "length" not in spec:
        raise SpecConfigError(
            "a design needs a contig or a length: pass --contigs/--length, or "
            "include a 'contig'/'length' field in --extra-spec"
        )
    return spec


def _build_create_specs(
    ctx: ManifestCtx[RFD3Args], extra_fields: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    """Iterate the input table's --input-column: one design group per ready row."""
    specs: list[tuple[str, dict[str, Any]]] = []
    for name in ctx.ready.index:
        name = cast(str, name)
        input_path = Path(str(ctx.ready.at[name, ctx.args.input_column])).resolve()
        if not input_path.exists():
            print(f"{name}: MISSING {input_path} (skipping)")
            continue
        try:
            specs.append(
                (
                    name,
                    _build_spec(name, input_path, ctx.args, ctx.lookup, extra_fields),
                )
            )
        except SpecConfigError:
            # A run-wide misconfiguration hits every row identically: fail fast
            # instead of silently skipping the entire table.
            raise
        except ValueError as e:
            # One bad row (e.g. an unresolvable {expr}) shouldn't sink the whole
            # array: warn and skip it.
            print(f"{name}: {e} (skipping)")
    return specs


def _build_root_specs(
    ctx: ManifestCtx[RFD3Args], extra_fields: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    """Root run (no --table): a single design group, from --input-pdb or de-novo.

    Root means "start a fresh lineage without iterating a table column" -- NOT
    necessarily de-novo. With --input-pdb we diffuse that one structure (motif /
    partial diffusion of a PDB not yet in any table); without it we generate de-novo.
    """
    # {expr} placeholders resolve up the table lineage, which a root run doesn't have.
    flag_sources = [ctx.args.contigs, ctx.args.length]
    if any(
        s and _HAS_PLACEHOLDER.search(s) for s in flag_sources
    ) or _tree_has_placeholder(extra_fields):
        raise ValueError(
            "--contigs/--length/--extra-spec contain a {expr} placeholder, but this "
            "is a root run (no --table) with no table lineage to resolve it against. "
            "Use literal values, or run with --table to diffuse existing table rows."
        )

    if ctx.args.input_pdb is not None:
        input_path: Path | None = Path(ctx.args.input_pdb).resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"--input-pdb {input_path} does not exist.")
        name = f"{input_path.stem}_diff"
    else:
        input_path = None
        name = "denovo_diff"

    # A root run has no parent table for collect to iterate; record the group name
    # so `sapia collect` can find its outputs and rebuild its rows.
    ctx.write_meta(root_designs=[name])

    return [(name, _build_spec(name, input_path, ctx.args, ctx.lookup, extra_fields))]


def _cli_overrides(args: RFD3Args) -> str:
    """Assemble the run-wide rfd3 Hydra overrides string (same for every shard)."""
    overrides = [
        f"diffusion_batch_size={args.num_designs}",
        f"inference_sampler.num_timesteps={args.num_timesteps}",
        f"inference_sampler.step_scale={args.step_scale}",
    ]
    if args.symmetry is not None:
        overrides.append("inference_sampler.kind=symmetry")
    if args.low_memory:
        overrides.append("low_memory_mode=True")
    if args.ckpt_path:
        overrides.append(f"ckpt_path={args.ckpt_path}")
    overrides.extend(args.set)
    return " ".join(overrides)


def build_rfd3_manifest(ctx: ManifestCtx[RFD3Args]) -> list[tuple[str, ...]]:
    extra_fields = load_extra_spec(ctx.args.extra_spec)

    if ctx.args.table is None:
        specs = _build_root_specs(ctx, extra_fields)
    else:
        if ctx.args.input_pdb is not None:
            raise ValueError(
                "--input-pdb is only valid for a root run (no --table); with "
                "--table, inputs come from the table's --input-column. Drop one of them."
            )
        specs = _build_create_specs(ctx, extra_fields)

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
