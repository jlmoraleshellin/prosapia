"""Modal image for rfdiffusion (used by ``--executor modal``).

Mirrors RFdiffusion's own ``docker/Dockerfile``: the CUDA 11.6 runtime base and the
pinned dgl / torch / SE3Transformer stack it needs. The checkout stays at
``/app/RFdiffusion`` and is installed editable, so ``rfdiffusion`` resolves its
default model directory (``<package>/../../models``) to ``/app/RFdiffusion/models``
and no ``inference.model_directory_path`` override is needed.

Weights are not baked in (seven checkpoints, several GB). They live on a Volume
(``SAPIA_MODAL_VOLUME_RFDIFFUSION_MODELS``, default ``sapia-rfdiffusion-models``)
mounted at that same default path; populate it once from a container of this image:

    bash /app/RFdiffusion/scripts/download_models.sh /app/RFdiffusion/models

A ``--ckpt`` passed at submit time must then name a path under that directory, since
it is read at submit time and used inside the container.

Under modal the prelude skips site activation, so this image supplies what
``rfdiffusion.sh`` would otherwise get from the activation script: ``RFDIFFUSION_PYTHON``
(the interpreter) and ``RUN_INFERENCE`` (the absolute path to ``run_inference.py``,
required whenever the interpreter is pinned). Both belong in the activation script,
not in ``.env`` -- the run's ``.env`` reaches the container and would override them
with paths that only exist on your cluster.
"""

import modal

from prosapia.core.executors.modal import get_named_volume

RFDIFFUSION_DIR = "/app/RFdiffusion"
MODEL_DIR = f"{RFDIFFUSION_DIR}/models"
RESOURCES = {"gpu": "A10", "cpu": 8, "memory": "16G", "timeout": "04:00:00"}


def image() -> modal.Image:
    return (
        modal.Image.from_registry(
            "nvcr.io/nvidia/cuda:11.6.2-cudnn8-runtime-ubuntu20.04",
            # Upstream's Dockerfile uses 3.9. Modal's standalone Pythons start at
            # 3.10 and torch 1.12.1+cu116 stops at cp310, so 3.10 is the only
            # version that satisfies both.
            add_python="3.10",
        )
        # build-essential: a few pins (e.g. pyrsistent 0.19.3) publish no x86_64
        # cp310 wheel and build from the sdist.
        .apt_install("git", "wget", "build-essential")
        .run_commands(
            "git clone --depth 1 https://github.com/RosettaCommons/RFdiffusion "
            f"{RFDIFFUSION_DIR}"
        )
        # numpy first and pinned: torch 1.12 predates the numpy 2 ABI, and without
        # this pip resolves numpy>=2, which leaves torch's bridge dead. It fails late
        # and obscurely, as `RuntimeError: Numpy is not available` from .numpy().
        .pip_install("numpy<2")
        # dgl and torch ship CUDA-11.6 builds on their own indexes; the rest are the
        # Dockerfile's pins.
        .pip_install(
            "dgl==1.0.2+cu116",
            find_links="https://data.dgl.ai/wheels/cu116/repo.html",
        )
        .pip_install(
            "torch==1.12.1+cu116",
            extra_index_url="https://download.pytorch.org/whl/cu116",
        )
        .pip_install(
            "e3nn==0.3.3",
            "wandb==0.12.0",
            "pynvml==11.0.0",
            "decorator==5.1.0",
            "hydra-core==1.3.2",
            "pyrsistent==0.19.3",
            "git+https://github.com/NVIDIA/dllogger#egg=dllogger",
            # RFdiffusion and SE3Transformer both build from a plain setup.py.
            "setuptools",
            "wheel",
        )
        .run_commands(
            f"pip install --no-cache-dir {RFDIFFUSION_DIR}/env/SE3Transformer",
            # --no-deps: the pins above are the environment. -e: keep the import path
            # inside the checkout so the default model directory stays MODEL_DIR.
            f"pip install --no-cache-dir --no-deps -e {RFDIFFUSION_DIR}",
        )
        .env(
            {
                "DGLBACKEND": "pytorch",
                "RFDIFFUSION_PYTHON": "python3",
                "RUN_INFERENCE": f"{RFDIFFUSION_DIR}/scripts/run_inference.py",
            }
        )
    )


def volumes() -> dict[str, modal.Volume]:
    return {
        MODEL_DIR: get_named_volume(
            "SAPIA_MODAL_VOLUME_RFDIFFUSION_MODELS", "sapia-rfdiffusion-models"
        )
    }
