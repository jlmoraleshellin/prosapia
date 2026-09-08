# Using ProteinMPNN

`sapia run proteinmpnn` designs sequences for backbones with ProteinMPNN, spawning a new child db. It is a terse, fully-explicit interface over ProteinMPNN's per-chain helper syntax: one small mini-language drives it and nothing is inferred from the structure.

`sapia run proteinmpnn --help` is the authoritative flag list; this page covers that mini-language (chains, then positions) and how the array is distributed.

## Chains (`--chains-to-design`)

The chains you design, in ProteinMPNN order. `:` is an inclusive range, `,` separates:

```bash
--chains-to-design A:C,E     # -> "A B C E"
--chains-to-design A,C       # -> "A C" (non-contiguous)
--chains-to-design ''        # design all chains (default)
```

This one list feeds every per-chain helper (`--chain_list`).

## Positions (`--fixed-positions`, `--tied-positions`)

The same `:` range / `,` separator grammar, extended for positions: `/` breaks chains (its groups map **one-to-one** onto `--chains-to-design`, in order), `,` separates fragments within a chain, and `start:end` expands inclusively. `{...}` islands resolve up the lineage (`+ - * //` arithmetic); everything else is a literal integer:

```bash
--fixed-positions 9:23/10,11,18:20,22      # keep these FIXED (not redesigned)
--tied-positions  1:8/1:8                   # TIE across chains (symmetric)
--fixed-positions 24:{hairpin_length-1}/…   # arithmetic + lineage column
```

Positions are **1-indexed within each parsed chain** (ProteinMPNN renumbers every chain to 1..L), not original PDB numbering. Order is preserved and not de-duplicated; tied groups must be equal length and are tied index-parallel. Per-chain positions require `--chains-to-design` to map their groups onto.

## Symmetry shortcut

`--symmetry` is a homo-oligomer convenience with no single ProteinMPNN switch: it ties all chains (`make_tied_positions_dict --homooligomer 1`, chains auto-detected at run time) and designs every chain. Mutually exclusive with `--tied-positions`.

## Other knobs

- `--bias-aa "D:1.39 E:1.39"` — global AA composition bias, space-separated `AA:bias` pairs.
- `--set "--ca_only"` — forward a raw `protein_mpnn_run.py` flag verbatim (repeatable); also takes pre-made jsonl paths, e.g. `--set "--pssm_jsonl /path/pssm.jsonl"`.
- `--num-seq-per-target`, `--sampling-temp`, `--seed`, `--batch-size` — the standard sampling knobs.

## How the array is distributed

Designs enter as individuals, but the submitter **auto-groups** those with an identical signature — `(chains, fixed_positions, tie_mode, tied_positions)` — so each group runs as a **single batched `protein_mpnn_run` call with the model loaded once**. Groups are then bin-packed onto array tasks up to `--designs-per-task` designs each (default 10), and the subgroups on a task run sequentially on its one GPU.

This is what keeps walltime down: the model-load cost is paid **per group, not per design**. Because positions can resolve per-design via the lineage, two designs share a batch only when their *resolved* params match. Lower `--designs-per-task` for more parallelism (more, smaller tasks); raise it for fewer tasks.

## Example

```bash
# homo-oligomer redesign after boltz, larger tasks
sapia run proteinmpnn outputs/RUN --database boltz_db --db-label proteinmpnn_r2 \
    --input-column boltz_path --filter filters/filter1_after_boltz.py \
    --symmetry --designs-per-task 20 --num-seq-per-target 10
```
