"""Modal image for pyrosetta (used by ``--executor modal``).

PyRosetta is installed with ``pyrosetta-installer``, which downloads the release
wheel (~1.5 GB) from RosettaCommons at image-build time, so the first run of this
tool builds for several minutes and later runs reuse the cached image. Rosetta is
single-threaded, so each task gets one CPU and no GPU (the manifest builder sets
``gpus_per_task = 0``).

PyRosetta is free for non-commercial use; commercial use needs a Rosetta license.
"""

import modal

RESOURCES = {"cpu": 1, "memory": "4G", "timeout": "01:00:00"}


def image() -> modal.Image:
    return (
        modal.Image.debian_slim(python_version="3.12")
        .pip_install("pyrosetta-installer")
        .run_commands(
            "python -c 'import pyrosetta_installer; pyrosetta_installer.install_pyrosetta()'"
        )
    )
