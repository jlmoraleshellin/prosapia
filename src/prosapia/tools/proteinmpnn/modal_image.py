"""Modal image for proteinmpnn (used by ``--executor modal``).

The ProteinMPNN checkout ships its own weights, so the image is self-contained.
"""

import modal

RESOURCES = {"gpu": "L4", "cpu": 8, "memory": "8G", "timeout": "01:00:00"}


def image() -> modal.Image:
    return (
        modal.Image.debian_slim(python_version="3.12")
        .apt_install("git")
        .pip_install("torch", "numpy")
        .run_commands("git clone --depth 1 https://github.com/dauparas/ProteinMPNN /opt/ProteinMPNN")
        .env({"PROTEIN_MPNN": "/opt/ProteinMPNN"})
    )
