"""Submit a SLURM array to run ProteinMPNN on designs, spawning a new child db.

Designs are taken from the source db as individuals. To keep the GPU busy, the
submitter auto-groups designs whose params are identical -- the signature
``(chains, fixed_positions, tie_mode, tied_positions)`` -- so each group runs as a
single batched ``protein_mpnn_run`` call (model loaded once). Groups are then
bin-packed onto SLURM array tasks up to ``--designs-per-task`` designs each.

The pipeline (``parse_multiple_chains`` -> optional helper steps -> ``protein_mpnn_run``)
runs inline in ``proteinmpnn.sbatch``, once per group. Each helper step is opt-in
and gated by a flag below; anything else is deferred to the binary via repeatable
``--set`` (native flags and pre-made jsonl paths alike).

This is a terse, fully-explicit interface over ProteinMPNN's per-chain helper
syntax. Two small mini-languages drive it; nothing is derived from the structure.

Chain mini-language (``--chains-to-design``): the chains you design, in ProteinMPNN
order. ``:`` is an inclusive letter range, ``,`` separates:

    --chains-to-design A:C,E     # -> "A B C E"
    --chains-to-design A,C        # -> "A C" (non-contiguous)
    --chains-to-design ''         # design all chains (default)

This one list is passed as ``--chain_list`` to ``assign_fixed_chains`` and, for the
position flags below, to ``make_{fixed,tied}_positions_dict``.

Position mini-language (``--fixed-positions`` / ``--tied-positions``): ``/`` breaks
chains (its groups map one-to-one onto ``--chains-to-design``, in order), ``,``
separates fragments within a chain, ``start:end`` expands inclusively, a single
position passes through; db column expressions live in ``{...}`` islands (resolved
up the lineage with ``+ - * //`` arithmetic), everything else is a literal integer;
outer ``[...]`` optional:

    --fixed-positions 9:23/10,11,18:20,22    # -> "9 10 ... 23, 10 11 18 19 20 22"
    --tied-positions  1:8/1:8                # -> "1 2 3 4 5 6 7 8, 1 2 3 4 5 6 7 8"
    --fixed-positions 24:{hairpin_length-1}/…  # arithmetic + lineage column

Positions are 1-indexed within each parsed chain (ProteinMPNN renumbers every chain
to 1..L), NOT original PDB numbering. Order is preserved and NOT de-duplicated (tied
positions are index-parallel: group j's i-th entry ties to group 0's i-th entry).
The user is responsible for aligning group counts to chains and keeping tied groups
equal length; ProteinMPNN raises on a mismatch.

Symmetry (``--symmetry``): homo-oligomer convenience with no ProteinMPNN equivalent
as a single switch -- ties all chains via ``make_tied_positions_dict --homooligomer 1``
(chains auto-detected at run time) and designs every chain. Mutually exclusive with
``--tied-positions``.

Other generalized knobs:
    --bias-aa "D:1.39 E:1.39" global AA composition bias (make_bias_AA); space-
                              separated AA:bias pairs. Empty = no bias.
    --set "--ca_only"         forward a raw protein_mpnn_run.py flag verbatim
                              (repeatable); also accepts pre-made jsonl paths, e.g.
                              --set "--pssm_jsonl /path/pssm.jsonl".

Usage:
    # after diffusion, an explicit per-chain design (reproduces upstream example 5)
    python run_proteinmpnn_sbatch.py outputs/<run> --database diffusion_db --db-label mpnn_seqs \\
        --chains-to-design A,C --fixed-positions 9:23/10,11,18:20,22 --tied-positions 1:8/1:8

    # after boltz, a homo-oligomer (reproduces upstream example 6), larger tasks
    python run_proteinmpnn_sbatch.py outputs/<run> --database mpnn_seqs_db --db-label mpnn_seqs_r2 \\
        --input-column boltz_path --filter filters/filter1_after_boltz.py \\
        --symmetry --designs-per-task 20 --num-seq-per-target 10
"""

import json
from argparse import ArgumentParser
from collections import defaultdict
from pathlib import Path
from typing import cast

from prosapia.core import (
    CommonArgs,
    LookupFn,
    ManifestCtx,
    ensure_pdb,
    resolve_template,
)


class ProteinMPNNArgs(CommonArgs):
    chains_to_design: str
    fixed_positions: str
    tied_positions: str
    symmetry: bool
    bias_aa: str
    set: list[str]
    num_seq_per_target: int
    sampling_temp: str
    seed: int
    batch_size: int
    designs_per_task: int


def _parse_chains(spec: str) -> str:
    """Expand the chain mini-language into a space-separated chain list.

    ``:`` is an inclusive letter range and ``,`` separates: ``A:C,E`` -> ``"A B C E"``.
    Order is preserved (no sort/dedupe). Empty spec -> "" (design all chains).
    """
    spec = spec.strip().strip("[]").strip()
    if not spec:
        return ""

    chains: list[str] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        ends = [e.strip() for e in token.split(":")]
        if len(ends) == 1:
            start = end = ends[0]
        elif len(ends) == 2:
            start, end = ends
        else:
            raise ValueError(
                f"--chains-to-design: malformed chain range {token!r} "
                f"(expected 'A' or 'A:C')"
            )
        if not (
            len(start) == 1 and len(end) == 1 and start.isalpha() and end.isalpha()
        ):
            raise ValueError(
                f"--chains-to-design: chain range {token!r} must use single letters "
                f"(e.g. 'A:C')"
            )
        lo, hi = ord(start.upper()), ord(end.upper())
        if hi < lo:
            raise ValueError(
                f"--chains-to-design: chain range {token!r} ends before it starts"
            )
        chains.extend(chr(c) for c in range(lo, hi + 1))
    return " ".join(chains)


def _pos_int(tok: str, token: str, name: str) -> int:
    """Parse a resolved position endpoint to int with a migration-friendly error."""
    try:
        return int(tok)
    except ValueError:
        raise ValueError(
            f"design {name!r}: non-integer position {tok!r} in {token!r} "
            f"(wrap db column expressions in braces, e.g. '{{motif_end}}')"
        )


def _parse_positions(spec: str, lookup: LookupFn, name: str) -> str:
    """Expand the position mini-language into a ProteinMPNN ``--position_list``.

    Expressions live in ``{...}`` islands and are resolved first (integers, bare
    db column names up the lineage, and ``+ - * //``); everything else is this
    tool's own mini-language: ``/`` breaks chains (-> the comma between per-chain
    groups), ``,`` separates fragments within a chain (-> spaces), ``start:end``
    expands inclusively, a single position passes through; outer ``[...]`` optional.

    Order is preserved and positions are NOT de-duplicated -- tied positions are
    index-parallel (group j's i-th entry ties to group 0's i-th entry). Empty spec
    -> "". Only a malformed range token (more than one ':') is rejected; alignment
    and validity are left to ProteinMPNN.
    """
    spec = resolve_template(spec, lookup, name).strip().strip("[]").strip()
    if not spec:
        return ""

    groups: list[str] = []
    for chain_spec in spec.split("/"):
        positions: list[int] = []
        for token in chain_spec.split(","):
            token = token.strip()
            if not token:
                continue
            ends = token.split(":")
            if len(ends) == 1:
                start = end = _pos_int(ends[0], token, name)
            elif len(ends) == 2:
                start = _pos_int(ends[0], token, name)
                end = _pos_int(ends[1], token, name)
            else:
                raise ValueError(
                    f"design {name!r}: malformed position range {token!r} "
                    f"(expected 'start:end' or a single position)"
                )
            positions.extend(range(start, end + 1))
        groups.append(" ".join(str(p) for p in positions))
    return ", ".join(groups)


def _write_bias_jsonl(spec: str, out_dir: Path) -> str:
    """Write a global AA-bias jsonl from a ``AA:bias`` spec; return its path.

    ``make_bias_AA.py`` is purely generative (no structure input), so we write the
    dict directly (format ``{"D": 1.39, ...}``) and avoid needing the ProteinMPNN
    env on the submit node. Empty spec => no bias (returns "").
    """
    spec = spec.strip()
    if not spec:
        return ""
    bias: dict[str, float] = {}
    for token in spec.split():
        if ":" not in token:
            raise ValueError(
                f"--bias-aa: malformed pair {token!r} (expected 'AA:bias', "
                f"e.g. 'D:1.39')"
            )
        aa, value = token.split(":", 1)
        try:
            bias[aa] = float(value)
        except ValueError:
            raise ValueError(f"--bias-aa: bias for {aa!r} is not a number: {value!r}")
    bias_path = out_dir / "bias_AA.jsonl"
    with open(bias_path, "w") as f:
        f.write(json.dumps(bias) + "\n")
    return str(bias_path)


def _mpnn_extra(args: ProteinMPNNArgs, bias_path: str) -> str:
    """Assemble the run-wide protein_mpnn_run.py argv tail (same for every design).

    Typed run flags, then the bias jsonl (if any), then verbatim ``--set`` tokens
    (native flags or pre-made jsonl paths).
    """
    parts = [
        "--num_seq_per_target",
        str(args.num_seq_per_target),
        "--sampling_temp",
        args.sampling_temp,
        "--seed",
        str(args.seed),
        "--batch_size",
        str(args.batch_size),
    ]
    if bias_path:
        parts += ["--bias_AA_jsonl", bias_path]
    parts.extend(args.set)
    return " ".join(parts)


# A design ready to run, and the (chains, fixed_positions, tie_mode, tied_positions)
# signature that decides which designs can share one batched protein_mpnn_run call.
Member = tuple[str, Path]  # (design_name, staged_pdb_source)
Signature = tuple[str, str, str, str]
Subgroup = tuple[Signature, list[Member]]


def _pack_subgroups(chunks: list[Subgroup], max_per_task: int) -> list[list[Subgroup]]:
    """First-fit-pack subgroup chunks (each <= max_per_task) into tasks.

    Each task holds at most ``max_per_task`` designs total, possibly spanning
    several signatures; every subgroup stays intact so batching is preserved.
    """
    tasks: list[list[Subgroup]] = []
    remaining: list[int] = []
    for chunk in chunks:
        size = len(chunk[1])
        for t, cap in enumerate(remaining):
            if size <= cap:
                tasks[t].append(chunk)
                remaining[t] -= size
                break
        else:
            tasks.append([chunk])
            remaining.append(max_per_task - size)
    return tasks


def _symlink_member(pdb_src: Path, inputs_dir: Path, name: str) -> None:
    """Symlink a staged design into ``inputs_dir`` as ``<name>.pdb`` (no copy)."""
    link = inputs_dir / f"{name}.pdb"
    if not link.exists() and not link.is_symlink():
        link.symlink_to(pdb_src)


def build_proteinmpnn_manifest(
    ctx: ManifestCtx[ProteinMPNNArgs],
) -> list[tuple[str, ...]]:
    df, args, out_dir, lookup = ctx.df, ctx.args, ctx.out_dir, ctx.lookup

    input_status_col = args.input_column.replace("_path", "_status")
    ready = df[df[input_status_col] == "OK"] if input_status_col in df.columns else df
    ready = ready[ready[args.input_column].notna() & (ready[args.input_column] != "")]

    # Run-wide pieces (all structure-independent): argv tail and the chain list.
    bias_path = _write_bias_jsonl(args.bias_aa, out_dir)
    mpnn_extra = _mpnn_extra(args, bias_path)
    chains = _parse_chains(args.chains_to_design)

    # Guardrails: tying is either the homo-oligomer shortcut or explicit, not both;
    # per-chain positions need a chain list to map their groups onto.
    if args.symmetry and args.tied_positions:
        raise ValueError(
            "--symmetry (homo-oligomer tie) and --tied-positions (explicit tie) are "
            "mutually exclusive"
        )
    if (args.fixed_positions or args.tied_positions) and not chains:
        raise ValueError(
            "--fixed-positions/--tied-positions require --chains-to-design (their "
            "groups map one-to-one onto those chains)"
        )

    # Stage each design (CIF->PDB via the shared cache; PDBs returned as-is) and
    # compute its signature. Positions may resolve per-design via lineage, so grouping
    # by signature lets same-param designs share one batched protein_mpnn_run call.
    groups: dict[Signature, list[Member]] = defaultdict(list)
    for design_name in sorted(cast(str, n) for n in ready.index):
        input_path = Path(str(ready.at[design_name, args.input_column]))
        pdb_src = ensure_pdb(input_path, args.run_dir).resolve()
        fixed_pl = _parse_positions(args.fixed_positions, lookup, design_name)
        if args.symmetry:
            tie_mode, tied_pl = "homo", ""
        elif args.tied_positions:
            tie_mode, tied_pl = (
                "explicit",
                _parse_positions(args.tied_positions, lookup, design_name),
            )
        else:
            tie_mode, tied_pl = "", ""
        sig: Signature = (chains, fixed_pl, tie_mode, tied_pl)
        groups[sig].append((design_name, pdb_src))

    # Split each signature group into subgroups of <= X, then bin-pack subgroups
    # into array tasks with a total budget of X designs each.
    x = args.designs_per_task
    chunks: list[Subgroup] = []
    for sig, members in groups.items():
        for i in range(0, len(members), x):
            chunks.append((sig, members[i : i + x]))
    tasks = _pack_subgroups(chunks, x)

    # Materialize: one grp_<g>/ output dir per subgroup (inputs/ holds symlinks), one
    # sub-manifest per task (a row per subgroup), and a 1-field top-level row per task.
    tasks_dir = out_dir / "proteinmpnn_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[tuple[str, ...]] = []
    gid = 0
    for t, subgroups in enumerate(tasks):
        sub_rows: list[tuple[str, ...]] = []
        for (chains_sig, fixed_pl, tie_mode, tied_pl), members in subgroups:
            grp_dir = out_dir / f"grp_{gid}"
            inputs_dir = grp_dir / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            for name, pdb_src in members:
                _symlink_member(pdb_src, inputs_dir, name)
            sub_rows.append(
                (
                    str(grp_dir),
                    chains_sig,
                    fixed_pl,
                    tie_mode,
                    tied_pl,
                    mpnn_extra,
                )
            )
            gid += 1
        task_file = tasks_dir / f"task_{t}.tsv"
        with open(task_file, "w") as f:
            for row in sub_rows:
                f.write("\t".join(row) + "\n")
        manifest_rows.append((str(task_file),))

    return manifest_rows


def add_proteinmpnn_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--designs-per-task",
        type=int,
        default=10,
        help="Max designs per SLURM array task (default 10). Designs are auto-grouped "
        "by identical params (chains, fixed/tied positions, symmetry) so a group shares "
        "one batched protein_mpnn_run call, and groups are bin-packed up to this budget. "
        "Lower it for more parallelism, raise it for fewer tasks.",
    )
    parser.add_argument(
        "--chains-to-design",
        type=str,
        default="",
        help="Chains to design, in ProteinMPNN order, as a chain mini-language: ':' is "
        "an inclusive letter range and ',' separates (e.g. 'A:C,E' -> 'A B C E'). Passed "
        "as --chain_list to assign_fixed_chains and, for the position flags, to "
        "make_{fixed,tied}_positions_dict. Empty (default): design all chains.",
    )
    parser.add_argument(
        "--fixed-positions",
        type=str,
        default="",
        help="Positions to keep FIXED (not redesigned), as a position mini-language: "
        "'/' breaks chains (groups map one-to-one onto --chains-to-design, in order), "
        "',' separates fragments within a chain, 'start:end' is an inclusive range; db "
        "column expressions go in {...} islands (resolved up the lineage with + - * // "
        "arithmetic), everything else is a literal integer. 1-indexed within each parsed "
        "chain. E.g. '9:23/10,11,18:20,22'. Empty (default): redesign everything.",
    )
    parser.add_argument(
        "--tied-positions",
        type=str,
        default="",
        help="Positions to TIE across chains for symmetric design, same position "
        "mini-language as --fixed-positions (groups map to --chains-to-design; tied "
        "groups must be equal length and are tied index-parallel). E.g. '1:8/1:8'. "
        "Mutually exclusive with --symmetry. Empty (default): no explicit tie.",
    )
    parser.add_argument(
        "--symmetry",
        action="store_true",
        help="Homo-oligomer convenience: tie all chains via make_tied_positions_dict "
        "--homooligomer 1 (chains auto-detected at run time; designs all chains). "
        "Mutually exclusive with --tied-positions.",
    )
    parser.add_argument(
        "--bias-aa",
        type=str,
        default="",
        help="Global AA composition bias as space-separated AA:bias pairs "
        "(e.g. 'D:1.39 E:1.39 K:1.39'), applied via make_bias_AA/--bias_AA_jsonl. "
        "Empty (default): no bias.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="FLAG",
        help="Raw flag forwarded verbatim to protein_mpnn_run.py (repeatable); also "
        "accepts pre-made jsonl paths. E.g. --set '--ca_only', --set '--omit_AAs C', "
        "--set '--pssm_jsonl /path/pssm.jsonl'.",
    )
    parser.add_argument("--num-seq-per-target", type=int, default=2)
    parser.add_argument("--sampling-temp", type=str, default="0.2")
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--batch-size", type=int, default=1)
