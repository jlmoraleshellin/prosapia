"""Small read-only queries over an input structure, shared by the tools."""

from pathlib import Path

import gemmi


def polymer_chain_names(pdb_path: Path) -> list[str]:
    """Return the first model's polymer chain names, in file order.

    The order is the one every downstream parser sees, and the names are read
    rather than generated: a structure's chains are not guaranteed to be a
    sequential ``A``, ``B``, ``C`` run. Non-polymer chains (ligands, waters) are
    skipped. Raises ``ValueError`` when the structure has no polymer chain.
    """
    structure = gemmi.read_structure(str(pdb_path))
    structure.setup_entities()
    names = [chain.name for chain in structure[0] if len(chain.get_polymer()) > 0]
    if not names:
        raise ValueError(f"{pdb_path}: no polymer chains found")
    return names


def count_polymer_chains(pdb_path: Path) -> int:
    """Number of polymer chains in the first model (a cyclic symmetry order)."""
    return len(polymer_chain_names(pdb_path))
