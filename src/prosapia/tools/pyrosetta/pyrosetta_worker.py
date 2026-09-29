#!/usr/bin/env python3
"""
Score one design's structure with PyRosetta.

This is the per-array-task step of the pyrosetta tool (and works standalone for a
single design). It loads the structure, optionally FastRelaxes it, and records:

    total_score      total energy (REU) of the scored pose
    score_per_res    total_score / number of residues
    score_raw        total energy before relax (== total_score when not relaxed)
    relax_ca_rmsd    CA RMSD between the input and the relaxed pose
    n_res, n_chains  size of the pose
    <term>           every nonzero-weighted score term, weighted (fa_atr, fa_rep, ...)
    sasa             total SASA (A^2, 1.4 A probe)
    sasa_hydrophobic hydrophobic SASA (A^2)
    packstat         RosettaHoles packing score (0-1, higher is better packed)
    buried_unsat     buried unsatisfied polar atoms
    dssp             DSSP secondary-structure string
    if_*             InterfaceAnalyzer metrics, only with --interface

Writes the scored pose to --out-pdb and a one-row TSV (name, status, scored_path,
metrics...) that collect_pyrosetta.py merges back into the table. Errors are
recorded as data (a status starting with 'error:') rather than only crashing, so
partial array runs still collect.

Normally invoked per array task by the pyrosetta tool -- run
``sapia run pyrosetta`` rather than calling this directly.

Usage (standalone, single design):
    python pyrosetta_worker.py --name foo --pdb foo.pdb --relax-cycles 1 \\
        --out-pdb foo_scored.pdb --result-tsv foo.tsv [--interface A_B]
"""

import argparse
import csv
from pathlib import Path
from typing import Any

INIT_FLAGS = "-mute all -ignore_unrecognized_res -ignore_zero_occupancy false"


def _interface_spec(pose: Any, interface: str) -> str:
    """Resolve 'auto' to '<first chain>_<other chains>'; pass anything else through."""
    if interface != "auto":
        return interface
    info = pose.pdb_info()
    chains = [info.chain(pose.chain_begin(i)) for i in range(1, pose.num_chains() + 1)]
    if len(chains) < 2:
        raise ValueError("--interface auto needs at least two chains")
    return f"{chains[0]}_{''.join(dict.fromkeys(chains[1:]))}"


def relax(pose: Any, sfxn: Any, cycles: int, constrain: bool) -> None:
    from pyrosetta import rosetta

    fast_relax = rosetta.protocols.relax.FastRelax(sfxn, cycles)
    if constrain:
        fast_relax.constrain_relax_to_start_coords(True)
        fast_relax.ramp_down_constraints(False)
    fast_relax.apply(pose)


def score_metrics(pose: Any, sfxn: Any) -> dict[str, Any]:
    from pyrosetta import rosetta

    metrics: dict[str, Any] = {}
    total = sfxn(pose)
    metrics["total_score"] = total
    metrics["score_per_res"] = total / pose.total_residue()
    metrics["n_res"] = pose.total_residue()
    metrics["n_chains"] = pose.num_chains()

    energies = pose.energies().total_energies()
    for st in sfxn.get_nonzero_weighted_scoretypes():
        term = rosetta.core.scoring.name_from_score_type(st)
        metrics[term] = sfxn.get_weight(st) * energies[st]

    metrics["sasa"] = rosetta.core.scoring.calc_total_sasa(pose, 1.4)
    hydrophobic = rosetta.core.simple_metrics.metrics.SasaMetric()
    hydrophobic.set_sasa_metric_mode(
        rosetta.core.scoring.sasa.SasaMethodHPMode.HYDROPHOBIC_SASA
    )
    metrics["sasa_hydrophobic"] = hydrophobic.calculate(pose)
    metrics["packstat"] = rosetta.core.scoring.packstat.compute_packing_score(pose, 0)
    metrics["buried_unsat"] = (
        rosetta.protocols.simple_filters.BuriedUnsatHbondFilter().compute(pose)
    )
    metrics["dssp"] = rosetta.core.scoring.dssp.Dssp(pose).get_dssp_secstruct()
    return metrics


def interface_metrics(pose: Any, sfxn: Any, interface: str) -> dict[str, Any]:
    from pyrosetta import rosetta

    partners = rosetta.core.pose.DockingPartners.docking_partners_from_string(
        _interface_spec(pose, interface)
    )
    analyzer = rosetta.protocols.analysis.InterfaceAnalyzerMover(partners)
    analyzer.set_scorefunction(sfxn)
    analyzer.set_pack_separated(True)
    analyzer.set_compute_packstat(True)
    analyzer.apply(pose.clone())
    data = analyzer.get_all_data()
    return {
        "if_dG": analyzer.get_interface_dG(),
        "if_dSASA": analyzer.get_interface_delta_sasa(),
        "if_dG_per_dSASA": data.dG_dSASA_ratio * 100.0,
        "if_hbonds": data.interface_hbonds,
        "if_delta_unsat": analyzer.get_interface_delta_hbond_unsat(),
        "if_n_res": analyzer.get_num_interface_residues(),
        "if_sc": data.sc_value,
        "if_packstat": data.packstat,
    }


def _write_result(result_tsv: Path, row: dict[str, Any]) -> None:
    result_tsv.parent.mkdir(parents=True, exist_ok=True)
    with open(result_tsv, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(row.keys())
        writer.writerow(row.values())


class Args(argparse.Namespace):
    name: str
    pdb: Path
    relax_cycles: int
    constrain_relax: bool
    interface: str
    scorefxn: str
    out_pdb: Path
    result_tsv: Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Score one structure with PyRosetta.")
    ap.add_argument("--name", required=True)
    ap.add_argument("--pdb", type=Path, required=True, help="Structure to score.")
    ap.add_argument("--relax-cycles", type=int, default=1)
    ap.add_argument("--constrain-relax", action="store_true")
    ap.add_argument("--interface", default="")
    ap.add_argument("--scorefxn", default="ref2015")
    ap.add_argument("--out-pdb", type=Path, required=True, help="Scored PDB to write.")
    ap.add_argument(
        "--result-tsv", type=Path, required=True, help="Per-design result TSV to write."
    )
    args = ap.parse_args(namespace=Args())

    try:
        if not args.pdb.exists():
            raise FileNotFoundError(f"structure missing: {args.pdb}")

        import pyrosetta
        from pyrosetta import rosetta

        pyrosetta.init(INIT_FLAGS)
        pose = pyrosetta.pose_from_pdb(str(args.pdb))
        sfxn = pyrosetta.create_score_function(args.scorefxn)

        score_raw = sfxn(pose)
        relax_rmsd = 0.0
        if args.relax_cycles > 0:
            start = pose.clone()
            relax(pose, sfxn, args.relax_cycles, args.constrain_relax)
            relax_rmsd = rosetta.core.scoring.CA_rmsd(start, pose)

        metrics = score_metrics(pose, sfxn)
        metrics["score_raw"] = score_raw
        metrics["relax_ca_rmsd"] = relax_rmsd
        if args.interface:
            metrics.update(interface_metrics(pose, sfxn, args.interface))

        args.out_pdb.parent.mkdir(parents=True, exist_ok=True)
        pose.dump_pdb(str(args.out_pdb))
        print(
            f"{args.name}: total_score {metrics['total_score']:.2f} "
            f"(raw {score_raw:.2f}, relax CA RMSD {relax_rmsd:.2f}) -> {args.out_pdb}"
        )
        _write_result(
            args.result_tsv,
            {"name": args.name, "status": "OK", "scored_path": str(args.out_pdb)}
            | metrics,
        )
    except Exception as e:
        print(f"{args.name}: ERROR {e}")
        # One line per TSV row, and short: pybind errors list every overload.
        message = " ".join(str(e).split())[:300]
        _write_result(
            args.result_tsv,
            {"name": args.name, "status": f"error: {message}", "scored_path": ""},
        )


if __name__ == "__main__":
    main()
