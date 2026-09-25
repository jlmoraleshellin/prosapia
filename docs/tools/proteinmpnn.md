# Using ProteinMPNN

`sapia run proteinmpnn` designs sequences for backbones with ProteinMPNN, spawning a new child table. It is a terse, fully-explicit interface over ProteinMPNN's per-chain helper syntax: one small mini-language drives it, and only `--symmetry` reads anything from the structure.

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

ProteinMPNN expects **one group per designed chain**, so a spec with fewer groups than chains is an error on its side (`fixed_position_dict[chain] = fixed_list[i]` → `IndexError`) — write every group out with `/`, or let `--symmetry` broadcast a single one.

## Symmetry shortcut (`--symmetry auto|N`)

`--symmetry` is a homo-oligomer convenience with no single ProteinMPNN switch. It does two things:

- **Ties all chains**, via `make_tied_positions_dict --homooligomer 1`.
- **Broadcasts a one-unit position spec.** A `--fixed-positions` spec with a single group describes one asymmetric unit, and it is replicated across the designed chains — so you write the unit once instead of repeating it per chain. Any other group count is passed through untouched.

The order comes from `auto` (the input structure's polymer chain count) or from a plain integer — for ProteinMPNN, symmetry is only ever a *number of tied chains*. With no `--chains-to-design`, the designed chains are the structure's first N, read from the file (chain names are not assumed to be a sequential `A`, `B`, `C` run).

```bash
# one 12-mer unit, written once
--fixed-positions 1:3,48:96 --symmetry auto
# same, with the order stated and the chains explicit
--fixed-positions 1:3,48:96 --symmetry 12 --chains-to-design A:L
```

Mutually exclusive with `--tied-positions`.

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
sapia run proteinmpnn outputs/RUN --table boltz_table --table-label proteinmpnn_r2 \
    --input-column boltz_path --filter filters/filter1_after_boltz.py \
    --symmetry auto --designs-per-task 20 --num-seq-per-target 10
```
