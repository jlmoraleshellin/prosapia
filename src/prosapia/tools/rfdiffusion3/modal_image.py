"""Modal image for rfdiffusion3 (used by ``--executor modal``).

Checkpoints live on a Volume (``SAPIA_MODAL_VOLUME_RFD3_CKPT``, default
``sapia-rfd3-checkpoints``) mounted at ``/checkpoints``; populate it once with
``foundry install rfd3 --checkpoint-dir /checkpoints`` from a container of this
image. An ``RFD3_CKPT`` override in ``.env`` must then be a path under
``/checkpoints``, since it is read at submit time and used inside the container.
"""

import modal

from prosapia.core.executors.modal import PYTHON_VERSION, named_volume

CHECKPOINT_DIR = "/checkpoints"
RESOURCES = {"gpu": "A100", "cpu": 8, "memory": "32G", "timeout": "04:00:00"}


def image() -> modal.Image:
    return (
        modal.Image.debian_slim(python_version=PYTHON_VERSION)
        .apt_install("git")
        .pip_install("rc-foundry[all]")
        .env({"FOUNDRY_CHECKPOINT_DIRS": CHECKPOINT_DIR})
    )


def volumes() -> dict[str, modal.Volume]:
    return {CHECKPOINT_DIR: named_volume("SAPIA_MODAL_VOLUME_RFD3_CKPT", "sapia-rfd3-checkpoints")}
