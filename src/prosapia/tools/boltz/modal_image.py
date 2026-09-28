"""Modal image for boltz (used by ``--executor modal``).

Boltz downloads its weights and CCD on first use into ``BOLTZ_CACHE``, which is a
Volume (``SAPIA_MODAL_VOLUME_BOLTZ_CACHE``, default ``sapia-boltz-cache``) so later
tasks reuse them.
"""

import modal

from prosapia.core.executors.modal import get_named_volume

CACHE_DIR = "/boltz_cache"
RESOURCES = {"gpu": "A100", "cpu": 24, "memory": "64G", "timeout": "08:00:00"}


def image() -> modal.Image:
    return (
        modal.Image.debian_slim(python_version="3.12")
        .pip_install("boltz[cuda]")
        .env({"BOLTZ_CACHE": CACHE_DIR})
    )


def volumes() -> dict[str, modal.Volume]:
    return {CACHE_DIR: get_named_volume("SAPIA_MODAL_VOLUME_BOLTZ_CACHE", "sapia-boltz-cache")}
