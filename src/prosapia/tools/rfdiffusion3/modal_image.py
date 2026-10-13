"""Modal image for rfdiffusion3 (used by ``--executor modal``).

Checkpoints live on a Volume (``SAPIA_MODAL_VOLUME_RFD3_CKPT``, default
``sapia-rfd3-checkpoints``) mounted at ``/checkpoints``; populate it once with
``foundry install rfd3 --checkpoint-dir /checkpoints`` from a container of this
image. The image sets ``FOUNDRY_CHECKPOINT_DIRS=/checkpoints`` so rfd3 finds them.
The tool has no checkpoint flag: ``rfdiffusion3.sh`` passes ``ckpt_path=$RFD3_CKPT`` at
task time, and only if that variable is exported (by an activation script on SLURM).
Do not put ``RFD3_CKPT`` in ``.env`` unless it is a path under ``/checkpoints``, since
``.env`` also reaches Modal tasks.

Pinned install
--------------
``rc-foundry`` is pinned to 0.2.0 and ``atomworks`` to ``<3``, with build-time import
checks after the install.
"""

import modal

from prosapia.core.executors.modal import get_named_volume

CHECKPOINT_DIR = "/checkpoints"
RESOURCES = {"gpu": "A10", "cpu": 8, "memory": "32G", "timeout": "04:00:00"}


def image() -> modal.Image:
    return (
        modal.Image.debian_slim(python_version="3.12")
        .apt_install("git")
        .pip_install("rc-foundry[all]==0.2.0", "atomworks<3")
        .run_commands(
            "python -c 'from atomworks.io.utils.bonds import get_inferred_polymer_bonds'",
            "python -c 'import rfd3.inference.input_parsing'",
            "pip freeze | grep -E '^(rc-foundry|atomworks|torch)='",
        )
        .env({"FOUNDRY_CHECKPOINT_DIRS": CHECKPOINT_DIR})
    )


def volumes() -> dict[str, modal.Volume]:
    return {CHECKPOINT_DIR: get_named_volume("SAPIA_MODAL_VOLUME_RFD3_CKPT", "sapia-rfd3-checkpoints")}
