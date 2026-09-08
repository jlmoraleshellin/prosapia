# Using RFdiffusion

`sapia run rfdiffusion` generates backbones with RFdiffusion. The tool injects only three overrides (`inference.input_pdb`, `inference.output_prefix`, `contigmap.contigs`) and defers everything else to RFdiffusion's own Hydra config plus whatever you add. So one interface covers de-novo, motif scaffolding, partial and symmetric diffusion: you pick the behavior with contigs and overrides, not a mode flag.

`sapia run rfdiffusion --help` is the authoritative flag list; this page covers the two things that aren't obvious: the contig language and how the array is distributed.

## Contigs, with `{expr}` placeholders

Contigs are authored in RFdiffusion's native contig syntax. Any `{expr}` island is resolved **per design** against the db lineage. It accepts integers, bare column names, and `+ - * //` arithmetic:

```bash
--contigs '[A1-{prebundle_length}/0 B1-{prebundle_length}/0]'
--contigs '{prepend_len},A1-{motif_end-1}'
```

A `{expr}` needs a lineage to resolve against, so it is only valid **with** `-d/--database`; a root run must use literal contigs.

### High-order symmetry: `--replicate`

Rather than writing every chain out, author one chain's unit by marking its fixed segment with the input chain letter `A` and let `--replicate` stamp it across chains, shifting `A → A, B, C, …` per copy while leaving diffused segments and chain breaks in place:

```bash
--contigs '[20/A1-{prebundle_length}/0]' --replicate auto
# -> [20/A1-.../0 20/B1-.../0 ... 20/K1-.../0]
```

`auto` derives the chain count from the input structure (same source as `--symmetry auto`, which derives `c<n_chains>`); or pass an explicit integer.

### Symmetric diffusion: `--symmetry`

`--symmetry` sets RFdiffusion's `inference.symmetry`, turning on its **symmetric diffusion**. `auto` derives `c<n_chains>` from the input structure's chain count; any other value is passed verbatim (`c2`, `D4`, …). Omitted by default (no symmetry constraint).

This is orthogonal to `--replicate`, and the two are easy to confuse:

- `--symmetry` is a **diffusion constraint**. It changes what RFdiffusion generates (symmetry-enforced backbones).
- `--replicate` is a **contig-authoring convenience**. It only expands your `--contigs` string across chains before submission; it does not by itself make the diffusion symmetric.

They are commonly used together: `--replicate` writes out the per-chain contig, and `--symmetry` tells RFdiffusion to enforce the point group over it.

## Root vs. create

- **Create** (with `-d/--database`): one diffusion per ready row, inputs from `--input-column`. Each input PDB is renumbered per-chain at submit time — RFdiffusion's continuous cross-chain numbering would otherwise break contig/symmetry parsing.
- **Root** (no `-d`): a single design group. Pass `--input-pdb` to diffuse one structure not yet in any db (motif / partial), or omit it for pure de-novo. `--input-pdb` is root-only.

## How the array is distributed

The submitter writes **one sub-manifest per array task**; the `.sbatch` reads its rows and launches them on the task's single GPU. Two levers shape the run, and they load the model differently:

| Lever | Effect | Model load |
| --- | --- | --- |
| `--num-designs N` | One `run_inference.py` process emits N designs from an input. | **Loaded once** for all N. |
| `--per-card N` | Packs N designs into one array task, launched **concurrently** on its one GPU (they time-share it). | Each design is its own process → its own load. Scale `--mem`/`-c` and watch VRAM. |

The model-reload cost is paid **per process, not per design**: raise `--num-designs` to amortize one load over many designs from the same input, and reach for `--per-card` only to saturate a GPU that a single diffusion leaves idle. Both run within one `--time` budget, so size them so the packed task finishes inside the walltime (override per run with `-t`).

## Other overrides

`--symmetry` (see [above](#symmetric-diffusion---symmetry)), `--partial-T`, `--num-designs`, `--ckpt`, Hydra `--config-name` / `--config-dir`, and repeatable `--set key=value` (the escape hatch for any option without a dedicated flag). Each is appended to `run_inference.py` only when set.

## Example

```bash
# partial-symmetric diffusion of existing db rows
sapia run rfdiffusion outputs/RUN --database db \
    --contigs '[A1-{prebundle_length}/0 B1-{prebundle_length}/0]' \
    --symmetry auto --partial-T 20 --num-designs 10 \
    --ckpt "$RFDIFFUSION/models/Complex_base_ckpt.pt"
```
