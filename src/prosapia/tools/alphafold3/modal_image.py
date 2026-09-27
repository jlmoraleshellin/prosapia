"""Modal image for alphafold3 (used by ``--executor modal``).

AlphaFold3 has no public image and its weights are licensed per user, so all of it
is supplied by you:

- ``SAPIA_MODAL_AF3_IMAGE``: a registry tag of an image built from the AF3 repo's
  Dockerfile. Its Python must match the one running ``sapia`` (see PYTHON_VERSION).
- ``SAPIA_MODAL_VOLUME_AF3_PARAMS`` (default ``sapia-af3-params``): model params,
  mounted at ``/root/models``.
- ``SAPIA_MODAL_VOLUME_AF3_DB`` (default ``sapia-af3-db``): public databases,
  mounted at ``/root/public_databases``.

Under modal, alphafold3.sh runs ``run_alphafold.py`` directly in this image
instead of through ``singularity exec``.
"""

import os

import modal

from prosapia.core.executors.modal import named_volume

RESOURCES = {"gpu": "A100-80GB", "cpu": 24, "memory": "64G", "timeout": "04:00:00"}


def image() -> modal.Image:
    tag = os.environ.get("SAPIA_MODAL_AF3_IMAGE")
    if not tag:
        raise RuntimeError(
            "Set SAPIA_MODAL_AF3_IMAGE in your .env to a registry tag of an "
            "AlphaFold3 image built from the AF3 repo's Dockerfile."
        )
    return modal.Image.from_registry(tag)


def volumes() -> dict[str, modal.Volume]:
    return {
        "/root/models": named_volume("SAPIA_MODAL_VOLUME_AF3_PARAMS", "sapia-af3-params"),
        "/root/public_databases": named_volume("SAPIA_MODAL_VOLUME_AF3_DB", "sapia-af3-db"),
    }
