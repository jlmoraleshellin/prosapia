"""Modal image for colabfold (used by ``--executor modal``).

AlphaFold2 weights are downloaded on first use into colabfold's data dir, which is
a Volume (``SAPIA_MODAL_VOLUME_COLABFOLD_DATA``, default ``sapia-colabfold-data``)
so later tasks reuse them.
"""

import modal

from prosapia.core.executors.modal import PYTHON_VERSION, get_named_volume

DATA_DIR = "/root/.cache/colabfold"
RESOURCES = {"gpu": "A100", "cpu": 8, "memory": "32G", "timeout": "04:00:00"}


def image() -> modal.Image:
    return (
        modal.Image.debian_slim(python_version=PYTHON_VERSION)
        .apt_install("git")
        .pip_install("colabfold[alphafold]", "jax[cuda12]")
    )


def volumes() -> dict[str, modal.Volume]:
    return {DATA_DIR: get_named_volume("SAPIA_MODAL_VOLUME_COLABFOLD_DATA", "sapia-colabfold-data")}
