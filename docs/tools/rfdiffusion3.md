# Using RFdiffusion3

`sapia run rfdiffusion3` generates backbones with RFdiffusion3 (rfd3). Unlike RFdiffusion, rfd3 is **file-driven, like AF3**: one inputs JSON holds many designs as a `{design_name: InputSpecification}` dict, and one `rfd3 design` process is pointed at it. The tool builds each design's `InputSpecification` from your flags (`contig`, `input`, `length`, `symmetry`, `partial_t`) and defers everything else to rfd3's own config plus whatever you add. So one interface covers de-novo, motif scaffolding, partial and symmetric diffusion: you pick the behavior with the contig and the spec fields, not a mode flag.

`sapia run rfdiffusion3 --help` is the authoritative flag list; this page covers what isn't obvious: the contig language, how symmetry actually works, the `--extra-spec` escape hatch, and how the array is distributed.

## Contigs, with `{expr}` placeholders

Contigs are authored in rfd3's native contig syntax: indexed motif segments reference the input by chain+residue (`A40-60`), designed regions are bare numbers or ranges (`30`, `60-80`), and the section `/0` breaks chains (comma-delimited like any other section, e.g. `A1-100,/0,B1-50`). Any `{expr}` island is resolved **per design** against the table lineage. It accepts integers, bare column names, and `+ - * //` arithmetic:

```bash
--contigs 'A1-{motif_end},30'      # motif A1..motif_end + 30 designed residues
--contigs '20,A1-131'              # 20 designed residues + chain-A motif
```

A `{expr}` needs a lineage to resolve against, so it is only valid **with** `-t/--table`; a root run must use literal contigs (this also applies to `--length` and `--extra-spec`).

A design needs a `contig` **or** a `--length` (see [de-novo symmetric](#symmetric-diffusion---symmetry) below); the `contig` may also come from `--extra-spec` instead of `--contigs`.

## Symmetric diffusion: `--symmetry`

This is the biggest difference from RFdiffusion, and the easiest thing to get wrong. **In rfd3, symmetry is the model's job, not the contig's.** With `--symmetry` set, rfd3's symmetric sampler (`symmetry.id` + `inference_sampler.kind=symmetry`) replicates a **single asymmetric-unit** contig across the whole point group. You write one unit — never all the chains.

```bash
# a C11 symmetric scaffold: ONE unit's contig; the sampler builds all 11 copies
--contigs '20,A1-131' --symmetry C11
```

`--symmetry auto` derives `C<n_chains>` from the input structure's polymer chain count; any other value is used verbatim (`C11`, `D4`, …). Omitted by default (no symmetry).

> **There is no `--replicate` flag** (RFdiffusion has one). You don't need it: RFdiffusion's contig must enumerate every chain, so `--replicate` stamps `A → B, C, …` for you before submission — but rfd3's sampler does that replication internally from the single unit. Writing all the chains out *and* enabling symmetry mode would double-specify the assembly.

A **de-novo symmetric oligomer needs no contig at all** — just one subunit's `--length` and `--symmetry`:

```bash
# a de-novo C5 pentamer from a 100-residue subunit
sapia run rfdiffusion3 outputs/RUN --length 100 --symmetry C5
```

When there is an input motif, the tool also sets `is_symmetric_motif: true` (the motif is treated as already symmetrized); a de-novo symmetric run omits it.

## Extra spec fields: `--extra-spec`

The dedicated flags only cover the common `InputSpecification` fields. rfd3's spec has many more — `ligand`, `select_fixed_atoms`, `select_hotspots`, `redesign_motif_sidechains`, `select_buried`, and so on. Rather than a flag per field, `--extra-spec` points at a **YAML or JSON** file: a mapping of extra fields merged into **every** design's spec. String values (and keys) may embed the same `{expr}` placeholders, resolved per design.

```bash
sapia run rfdiffusion3 outputs/RUN --table table \
    --contigs 'A10-15,30,A16-20' --extra-spec my_extra.yaml
```

`my_extra.yaml` (an enzyme-style active-site scaffold with a fixed motif and a ligand):

```yaml
# Extra rfd3 InputSpecification fields, merged into every design.
ligand: "HAX,OAA"
select_fixed_atoms:
  "A{motif_start}": ALL       # {expr} resolved per design from the table lineage
  A15: BKBN
  A20: BKBN
partial_t: 10.0
```

The same file as JSON works identically:

```json
{
  "ligand": "HAX,OAA",
  "select_fixed_atoms": { "A{motif_start}": "ALL", "A15": "BKBN", "A20": "BKBN" },
  "partial_t": 10.0
}
```

**Collisions are an error.** If a field is set by both a dedicated flag and `--extra-spec` (`contig`, `input`, `length`, `symmetry`, `partial_t`), the run fails up front — pick one source. Native YAML/JSON types are preserved (an int stays an int); only strings containing `{expr}` are rewritten.

## Root vs. create

- **Create** (with `-t/--table`): one design group per ready row, inputs from `--input-column`. The input PDB/CIF is used as-is — rfd3 contigs reference the input's own chain+residue numbers, so no renumbering is done (unlike RFdiffusion).
- **Root** (no `-t`): a single design group. Pass `--input-pdb` to diffuse one structure not yet in any table (motif / partial), or omit it for pure de-novo. `--input-pdb` is root-only, and a root run can't use `{expr}` (no lineage).

## How the array is distributed

rfd3 iterates a multi-key inputs JSON **in series** inside one process, so batching is by **shard**, not by concurrent processes:

| Lever | Effect | Model load |
| --- | --- | --- |
| `--num-designs N` | Emits N designs per input key (`diffusion_batch_size`). | **Loaded once** for all N. |
| `--shard-size N` | Packs N design keys into one shard JSON / array task; the task's single `rfd3 design` process runs them **in series** on its one GPU. | **Loaded once** per task, shared across its keys. |

Because one process serves a whole shard, `--shard-size` is memory-safe — there is no concurrent-process fan-out like RFdiffusion's `--per-card`. Size the shard so the task finishes inside `--time` (override per run with `-T`).

## Other overrides

`--num-timesteps` (`inference_sampler.num_timesteps`), `--step-scale` (`inference_sampler.step_scale`), `--partial-t` (per-design `partial_t`, ~5–15 Å), `--low-memory` (`low_memory_mode`), `--ckpt-path` (defaults to `$RFD3_CKPT`), and repeatable `--set key=value` (the escape hatch for any Hydra option without a dedicated flag, e.g. `--set n_batches=2`). Each is appended to `rfd3 design` only when set.

## Example

```bash
# symmetric motif scaffold on existing table rows: single-unit contig,
# the sampler builds the C-symmetric assembly derived from the input
sapia run rfdiffusion3 outputs/RUN --table table \
    --contigs '20,A1-{motif_end}' --symmetry auto \
    --num-designs 8 --shard-size 5 \
    --extra-spec active_site.yaml
```
