"""
Submit a SLURM array job to relax designs whose symmetry files are ready.

Reads the input directory name (default: symm) and derives _INPUT.pdb paths
next to each .symm file. The manifest contains (input_pdb, symm_path,
hairpin_length) per design.

Usage:
    python run_relax_batch.py outputs/20260420_123035_grow_hairpin
    python run_relax_batch.py outputs/20260420_123035_grow_hairpin --max-concurrent 10
"""

from pathlib import Path

from prosapia.core import CommonArgs, ManifestCtx


def build_relax_manifest(ctx: ManifestCtx[CommonArgs]) -> list[tuple[str, ...]]:
    df, args, out_dir = ctx.df, ctx.args, ctx.out_dir
    """Symmetric relax takes .symm paths as inputs and derives _INPUT.pdb
    paths next to each symm file by name"""
    ready = df[df[args.input_column].notna() & (df[args.input_column] != "")]

    output_status_col = f"{out_dir.name}_status"
    if output_status_col in ready.columns:
        ready = ready[ready[output_status_col] != "OK"]

    manifest_rows: list[tuple[str, ...]] = []
    for name in ready.index:
        # Columns to look for
        symm_pdb_path = Path(ready.at[name, args.input_column])  # type: ignore
        hairpin_length = int(ready.at[name, "hairpin_length"])  # type: ignore

        # Derived data
        input_pdb = (
            symm_pdb_path.parent
            / f"{symm_pdb_path.stem.replace('_symm', '')}_INPUT.pdb"
        )
        symm_path = (
            symm_pdb_path.parent / f"{symm_pdb_path.stem.replace('_symm', '')}.symm"
        )
        if not input_pdb.exists():
            print(f"{name}: MISSING {input_pdb} (skipping)")
            continue
        manifest_rows.append(tuple(map(str, (input_pdb, symm_path, hairpin_length))))

    return manifest_rows
