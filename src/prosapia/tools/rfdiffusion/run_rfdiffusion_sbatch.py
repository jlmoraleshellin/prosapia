"""
Submit a SLURM array job to run RFdiffusion on passing designs.

The tool injects only the three run-specific overrides -- ``inference.input_pdb``,
``inference.output_prefix`` and ``contigmap.contigs`` -- and defers everything else
to RFdiffusion's own Hydra config plus whatever overrides the user supplies. This
keeps it general: symmetric or not, partial or full diffusion.

Contigs are authored in RFdiffusion's native contig syntax, with ``{expr}``
placeholders resolved per-design against the database lineage (integers, bare
column names, and + - * // arithmetic; see pipeline_core.resolve_expr):

    --contigs '[A1-{prebundle_length}/0 B1-{prebundle_length}/0]'
    --contigs '{prepend_len},A1-{motif_end-1}'

For high-order symmetry, write one chain's unit -- marking its fixed segment
with the input chain letter A -- and let ``--replicate`` stamp it across chains,
shifting that letter A, B, C, ... per copy while leaving diffused segments and
chain breaks in place. E.g. an 11-mer without listing all 11 chains:

    --contigs '[20/A1-{prebundle_length}/0]' --replicate auto
    # -> [20/A1-.../0 20/B1-.../0 ... 20/K1-.../0]

Everything else is opt-in and appended to run_inference.py only when set:
``--symmetry`` (``auto`` derives c<n_chains> from the input), ``--partial-T``,
``--num-designs``, ``--ckpt``, ``--config-name`` / ``--config-dir`` (Hydra), and
repeatable ``--set key=value``. All per-design prep happens here at manifest-build
time (renumber + contig resolution); the sbatch just launches the binary.

With --per-card N, designs are chunked N at a time into per-task sub-manifests;
each array task runs its N diffusions concurrently on a single GPU.

Usage:
    # general run, config-driven
    sapia run rfdiffusion outputs/RUN --database db \\
        --contigs '[A1-{prebundle_length}/0]' --config-name base

    # reproduce the old partial-symmetric behavior
    sapia run rfdiffusion outputs/RUN --database db \\
        --contigs '[A1-{prebundle_length}/0 B1-{prebundle_length}/0]' \\
        --symmetry auto --partial-T 20 --num-designs 10 \\
        --ckpt "$RFDIFFUSION/models/Complex_base_ckpt.pt"
"""

import re
from argparse import ArgumentParser
from pathlib import Path
from typing import Callable, cast

import gemmi

from prosapia.core import CommonArgs, ManifestCtx, resolve_template

# A fixed contig segment references an input chain: an uppercase chain letter
# immediately followed by a residue number (e.g. A1-108). Diffused segments
# (bare ranges like 20) and chain breaks (0) have no leading letter, so they
# don't match and are copied verbatim during replication.
_CHAIN_REF = re.compile(r"\b([A-Z])(\d)")

# A {expr} placeholder island in the contig template, resolved per-design up the
# db lineage. Meaningless in a root run (no db), so we reject it there explicitly.
_HAS_PLACEHOLDER = re.compile(r"\{[^}]*\}")


class RFDiffArgs(CommonArgs):
    contigs: str
    input_pdb: Path | None
    replicate: str | int | None
    per_card: int
    symmetry: str | None
    partial_T: int | None
    num_designs: int | None
    ckpt: str | None
    config_name: str | None
    config_dir: str | None
    set: list[str]


def _replicate_arg(value: str) -> str | int:
    """argparse type for --replicate: the literal 'auto' or a positive int."""
    if value == "auto":
        return "auto"
    n = int(value)  # ValueError -> argparse reports an invalid-value error
    if n < 1:
        raise ValueError("must be >= 1")
    return n


def add_extra_args_rfdiffusion(parser: ArgumentParser):
    parser.add_argument(
        "--contigs",
        type=str,
        required=True,
        help="RFdiffusion contig template (contigmap.contigs). May embed {expr} "
        "placeholders resolved per-design up the lineage: integers, bare db column "
        "names, and + - * // arithmetic. "
        "E.g. '[A1-{prebundle_length}/0 B1-{prebundle_length}/0]'. "
        "With --replicate, author a single chain's unit and mark its fixed "
        "segment with the input chain letter A; diffused segments and chain "
        "breaks stay letterless (e.g. '[20/A1-{prebundle_length}/0]').",
    )
    parser.add_argument(
        "--input-pdb",
        type=Path,
        default=None,
        help="Single input structure to diffuse when starting a ROOT run (no "
        "--database): motif/partial diffusion of one PDB that isn't in any db yet. "
        "Only valid without --database (with a db, inputs come from --input-column). "
        "Omit for pure de-novo generation. The design group is named after this "
        "file's stem.",
    )
    parser.add_argument(
        "--replicate",
        type=_replicate_arg,
        default=None,
        metavar="auto|N",
        help="Replicate a single-chain --contigs unit across N chains, shifting "
        "each fixed segment's chain letter A, B, C, ... (diffused segments and "
        "chain breaks copied verbatim). 'auto' derives N from the input "
        "structure's chain count (same count as --symmetry auto). Handy for "
        "high-order symmetry (e.g. an 11-mer) so you don't write all chains out. "
        "Off by default (contigs used verbatim).",
    )
    parser.add_argument(
        "--per-card",
        type=int,
        default=1,
        help="Number of diffusions to run concurrently on a single GPU. They "
        "time-share the card, so scale --mem/--cpus-per-task accordingly and "
        "watch for VRAM OOM. Defaults to 1 (one diffusion per card).",
    )
    parser.add_argument(
        "--symmetry",
        type=str,
        default=None,
        help="inference.symmetry value. 'auto' derives c<n_chains> from the input "
        "structure; any other value is used verbatim (e.g. c2, D4). Omitted by "
        "default (no symmetry override).",
    )
    parser.add_argument(
        "--partial-T",
        type=int,
        default=None,
        help="diffuser.partial_T (partial-diffusion noising timesteps). Omitted by "
        "default (full diffusion / config default).",
    )
    parser.add_argument(
        "--num-designs",
        type=int,
        default=None,
        help="inference.num_designs generated per input. Omitted by default "
        "(config default).",
    )
    parser.add_argument(
        "--ckpt",
        type=str,
        default=None,
        help="inference.ckpt_override_path. Omitted by default (config default).",
    )
    parser.add_argument(
        "--config-name",
        type=str,
        default=None,
        help="RFdiffusion Hydra --config-name to run under (native or user config).",
    )
    parser.add_argument(
        "--config-dir",
        type=str,
        default=None,
        help="RFdiffusion Hydra --config-dir to search for a user-provided config.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra run_inference.py Hydra override, appended verbatim. Repeatable. "
        "Escape hatch for options without a dedicated flag.",
    )


def renumber_chains_independently(src: Path, dst: Path) -> None:
    """Write ``src`` to ``dst`` with each chain's residue numbering restarting at 1.

    RFdiffusion numbers residues continuously across chain boundaries (chain A
    1..N, chain B N+1..2N, ...). When the input is itself a prior diffusion
    output, that continuous numbering breaks the per-chain contig/symmetry
    parsing, so we renumber each chain to share the same 1..N numbering before
    running. Residues are renumbered in the order they appear; any insertion
    codes are dropped.
    """
    structure = gemmi.read_structure(str(src))
    for model in structure:
        for chain in model:
            for i, residue in enumerate(chain, start=1):
                residue.seqid = gemmi.SeqId(i, " ")
    dst.parent.mkdir(parents=True, exist_ok=True)
    structure.write_pdb(str(dst))


def _count_chains(pdb_path: Path) -> int:
    """Return the number of polymer chains in the first model (cyclic symmetry order)."""
    structure = gemmi.read_structure(str(pdb_path))
    structure.setup_entities()
    model = structure[0]
    return sum(1 for chain in model if len(chain.get_polymer()) > 0)


def _replicate_contig(unit_spec: str, n_chains: int) -> str:
    """Replicate a single asymmetric-unit spec across n chains (A, B, C, ...).

    ``unit_spec`` is one chain's contig (after placeholder resolution), with its
    fixed segment marked by the input chain letter A -- e.g. ``20/A1-108/0`` (a
    20-residue diffused segment, then fixed chain-A residues 1-108, then a chain
    break). Each replica shifts every chain-letter reference by its index
    (A -> A, B, C, ...) while leaving diffused segments and breaks untouched, and
    the copies are wrapped in brackets:

        ``[20/A1-108/0 20/B1-108/0 ... 20/K1-108/0]``

    A fully letterless unit (pure de novo symmetric oligomer) is replicated
    verbatim.
    """
    unit = unit_spec.strip().strip("[]").strip()
    replicas = [
        _CHAIN_REF.sub(lambda m, off=i: chr(ord(m.group(1)) + off) + m.group(2), unit)
        for i in range(n_chains)
    ]
    return "[" + " ".join(replicas) + "]"


def _symmetry_token(args: RFDiffArgs, n_chains: int | None) -> str:
    """Per-design inference.symmetry override (empty when --symmetry is unset)."""
    if args.symmetry is None:
        return ""
    value = f"c{n_chains}" if args.symmetry == "auto" else args.symmetry
    return f"inference.symmetry={value}"


def _global_extra(args: RFDiffArgs) -> str:
    """Run-wide run_inference.py args (same for every design), joined space-separated.

    Config flags first, then optional overrides, then verbatim --set tokens. The
    sbatch splits this back into separate argv tokens.
    """
    parts: list[str] = []
    if args.config_dir:
        parts.append(f"--config-dir {args.config_dir}")
    if args.config_name:
        parts.append(f"--config-name {args.config_name}")
    if args.partial_T is not None:
        parts.append(f"diffuser.partial_T={args.partial_T}")
    if args.num_designs is not None:
        parts.append(f"inference.num_designs={args.num_designs}")
    if args.ckpt:
        parts.append(f"inference.ckpt_override_path={args.ckpt}")
    parts.extend(args.set)
    return " ".join(parts)


def _assemble_design(
    name: str,
    staged_input: Path | None,
    args: RFDiffArgs,
    out_dir: Path,
    lookup: Callable[[str, str], object],
    global_extra: str,
) -> tuple[str, ...]:
    """Resolve one design's contig/symmetry/replicate and return its manifest tuple.

    ``staged_input`` is the already-renumbered input PDB, or ``None`` for a de-novo
    design (the sbatch then omits ``inference.input_pdb``, leaving the field empty).
    Raises ValueError on an unresolvable contig, or on an auto symmetry/replicate that
    needs a chain count but has no input structure to read one from.
    """
    contig = resolve_template(args.contigs, lookup, name)

    needs_chains = args.symmetry == "auto" or args.replicate == "auto"
    if not needs_chains:
        n_chains = None
    elif staged_input is None:
        raise ValueError(
            "--symmetry auto / --replicate auto need an input structure to count "
            "chains, but this design has none. Pass an explicit symmetry "
            "(e.g. c3) / replicate count, or provide --input-pdb."
        )
    else:
        n_chains = _count_chains(staged_input)

    if args.replicate is not None:
        n_rep = n_chains if args.replicate == "auto" else args.replicate
        contig = _replicate_contig(contig, cast(int, n_rep))

    symmetry_token = _symmetry_token(args, n_chains)
    output_prefix = out_dir / name / name

    return tuple(
        map(
            str,
            (
                name,
                staged_input or "",
                output_prefix,
                contig,
                symmetry_token,
                global_extra,
            ),
        )
    )


def _build_create_designs(
    ctx: ManifestCtx[RFDiffArgs], global_extra: str
) -> list[tuple[str, ...]]:
    """Iterate the input db's --input-column: one diffusion per ready design row."""
    df, args, out_dir = ctx.df, ctx.args, ctx.out_dir
    ready = df[df[args.input_column].notna() & (df[args.input_column] != "")]

    designs: list[tuple[str, ...]] = []
    for name in ready.index:
        name = cast(str, name)
        input_path = Path(str(ready.at[name, args.input_column]))
        if not input_path.exists():
            print(f"{name}: MISSING {input_path} (skipping)")
            continue

        # Prep (deterministic, input-derived): renumber the input per-chain into a
        # staged PDB so the sbatch only launches the binary.
        staged_input = out_dir / name / "_diffusion_input" / f"{name}_renumbered.pdb"
        renumber_chains_independently(input_path, staged_input)

        try:
            designs.append(
                _assemble_design(
                    name, staged_input, args, out_dir, ctx.lookup, global_extra
                )
            )
        except ValueError as e:
            # One bad row shouldn't sink the whole array: warn and skip it.
            print(f"{name}: {e} (skipping)")
    return designs


def _build_root_designs(
    ctx: ManifestCtx[RFDiffArgs], global_extra: str
) -> list[tuple[str, ...]]:
    """Root run (no --database): a single design group, from --input-pdb or de-novo.

    Root means "start a fresh lineage without iterating a db column" -- NOT
    necessarily de-novo. With --input-pdb we diffuse that one structure (motif /
    partial diffusion of a PDB not yet in any db); without it we generate de-novo.
    Either way it's one group -> one SLURM task.
    """
    args, out_dir = ctx.args, ctx.out_dir

    # {expr} placeholders resolve up the db lineage, which a root run doesn't have.
    if _HAS_PLACEHOLDER.search(args.contigs):
        raise ValueError(
            "--contigs contains a {expr} placeholder, but this is a root run "
            "(no --database) with no db lineage to resolve it against. Use literal "
            "contigs, or run with --database to diffuse existing db rows."
        )

    if args.input_pdb is not None:
        input_path = Path(args.input_pdb)
        if not input_path.exists():
            raise FileNotFoundError(f"--input-pdb {input_path} does not exist.")
        name = input_path.stem
        staged_input: Path | None = (
            out_dir / name / "_diffusion_input" / f"{name}_renumbered.pdb"
        )
        renumber_chains_independently(input_path, staged_input)
    else:
        name = "denovo"
        staged_input = None

    return [
        _assemble_design(name, staged_input, args, out_dir, ctx.lookup, global_extra)
    ]


def build_rfdiff_manifest(ctx: ManifestCtx[RFDiffArgs]) -> list[tuple[str, ...]]:
    args, out_dir = ctx.args, ctx.out_dir
    global_extra = _global_extra(args)

    if args.database is None:
        designs = _build_root_designs(ctx, global_extra)
    else:
        if args.input_pdb is not None:
            raise ValueError(
                "--input-pdb is only valid for a root run (no --database); with "
                "--database, inputs come from the db's --input-column. Drop one of them."
            )
        designs = _build_create_designs(ctx, global_extra)

    # One sub-manifest per task; the sbatch script launches its rows
    # concurrently on the task's single allocated GPU.
    task_dir = out_dir / "diffusion_tasks"
    task_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[tuple[str, ...]] = []
    for i in range(0, len(designs), args.per_card):
        chunk = designs[i : i + args.per_card]
        sub = task_dir / f"task_{i // args.per_card}.tsv"
        with open(sub, "w") as f:
            for row in chunk:
                f.write("\t".join(row) + "\n")
        manifest_rows.append((str(sub),))
    return manifest_rows
