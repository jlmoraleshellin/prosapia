"""Modal image for alphafold3 (used by ``--executor modal``).

AF3 v3.0.4 is built from source, following the repo's ``docker/Dockerfile``. Set
``SAPIA_MODAL_AF3_IMAGE`` to a registry tag to use a prebuilt image instead (AF3 at
``/app/alphafold``, ``python`` on PATH). The build needs network access to GitHub and
``files.wwpdb.org``.

Model parameters are licensed per user and never baked in. They come from Volumes:

- ``SAPIA_MODAL_VOLUME_AF3_PARAMS`` (default ``sapia-af3-params``): mounted at
  ``/root/models``.
- ``SAPIA_MODAL_VOLUME_AF3_DB`` (default ``sapia-af3-db``): the genetic databases,
  mounted at ``/root/public_databases``. Leave it empty to run database-free by giving
  every chain an MSA policy (``--no-msa`` / ``--msa-empty-chains`` / ``--msa-file``).

Under modal, ``alphafold3.sh`` runs ``run_alphafold.py`` with ``$AF3_PYTHON`` (the uv
venv below) instead of through ``singularity exec``.
"""

import os

import modal

from prosapia.core.executors.modal import get_named_volume

RESOURCES = {"gpu": "A100-80GB", "cpu": 24, "memory": "64G", "timeout": "04:00:00"}

AF3_REPO = "https://github.com/google-deepmind/alphafold3"
AF3_TAG = "v3.0.4"
AF3_SRC = "/app/alphafold"
AF3_VENV = "/alphafold3_venv"
AF3_PYTHON = f"{AF3_VENV}/bin/python"

UV_VERSION = "0.9.24"

HMMER_URL = "http://eddylab.org/software/hmmer/hmmer-3.4.tar.gz"
HMMER_SHA256 = "ca70d94fd0cf271bd7063423aabb116d42de533117343a9b27a65c17ff06fbf3"

# Bounds the C++ build; unbounded parallelism is the usual OOM.
BUILD_PARALLEL = "4"

BUILD_ENV = {
    "DEBIAN_FRONTEND": "noninteractive",
    "UV_COMPILE_BYTECODE": "1",
    "UV_PROJECT_ENVIRONMENT": AF3_VENV,
    "UV_LINK_MODE": "copy",
    "CMAKE_BUILD_PARALLEL_LEVEL": BUILD_PARALLEL,
    "MAKEFLAGS": f"-j{BUILD_PARALLEL}",
}


def _build_af3_image() -> modal.Image:
    return (
        # The CUDA `base` image ships no Python; add_python is for Modal's own runtime.
        # AF3 itself uses the uv venv below.
        modal.Image.from_registry(
            "nvidia/cuda:12.6.3-base-ubuntu24.04", add_python="3.12"
        )
        .apt_install(
            "python3.12",
            "python3.12-dev",
            "git",
            "wget",
            "gcc",
            "g++",
            "make",
            "zlib1g-dev",
            "zstd",
            "patch",
            "curl",
            "ca-certificates",
            "gzip",
            env=BUILD_ENV,
        )
        .run_commands(
            f"curl -LsSf https://astral.sh/uv/{UV_VERSION}/install.sh "
            "| env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh",
            env=BUILD_ENV,
        )
        # A full clone, not --depth 1: setuptools_scm reads the version from the tag.
        .run_commands(
            f"git clone --branch {AF3_TAG} {AF3_REPO} {AF3_SRC}",
            env=BUILD_ENV,
        )
        # HMMER 3.4 with AF3's jackhmmer --seq_limit patch. Symlinked into
        # /usr/local/bin because run_alphafold.py finds the binaries via shutil.which.
        .run_commands(
            "mkdir -p /hmmer_build /hmmer",
            f"wget {HMMER_URL} --directory-prefix /hmmer_build",
            f'cd /hmmer_build && echo "{HMMER_SHA256}  hmmer-3.4.tar.gz" '
            "| sha256sum --check",
            "cd /hmmer_build && tar zxf hmmer-3.4.tar.gz && rm hmmer-3.4.tar.gz",
            f"cd /hmmer_build && patch -p0 < {AF3_SRC}/docker/jackhmmer_seq_limit.patch",
            f"cd /hmmer_build/hmmer-3.4 && ./configure --prefix /hmmer "
            f"&& make -j{BUILD_PARALLEL} && make install",
            "cd /hmmer_build/hmmer-3.4/easel && make install",
            "ln -sf /hmmer/bin/* /usr/local/bin/",
            "rm -rf /hmmer_build",
            env=BUILD_ENV,
        )
        # Dependencies in their own layer so changes below don't redo the C++ build.
        .run_commands(
            f"uv venv --python /usr/bin/python3.12 {AF3_VENV}",
            f"cd {AF3_SRC} && uv sync --frozen --all-groups --no-editable",
            env=BUILD_ENV,
        )
        .run_commands(
            # setuptools_scm silently falls back to 3.0.2 if the clone lost its tag.
            f'V=$({AF3_PYTHON} -c "import importlib.metadata as m; '
            "print(m.version('alphafold3'))\"); "
            'case "$V" in 3.0.4*) ;; *) echo "expected alphafold3 3.0.4, got $V" '
            ">&2; exit 1;; esac",
            # Deviation from the Dockerfile's `uv run build_data`: uv re-syncs the
            # project first, which rebuilds AF3 as 3.0.5.dev0 and fails the build.
            f"cd {AF3_SRC} && {AF3_VENV}/bin/build_data",
            env=BUILD_ENV,
        )
        .env(
            {
                # Without this, XLA compilation time explodes (A100, compute 8.0).
                "XLA_FLAGS": "--xla_gpu_enable_triton_gemm=false",
                # Memory settings for folding up to 5,120 tokens on an A100 80 GB.
                "XLA_PYTHON_CLIENT_PREALLOCATE": "true",
                "XLA_CLIENT_MEM_FRACTION": "0.95",
                "AF3_PYTHON": AF3_PYTHON,
            }
        )
    )


def image() -> modal.Image:
    tag = os.environ.get("SAPIA_MODAL_AF3_IMAGE")
    if tag:
        return modal.Image.from_registry(tag)
    return _build_af3_image()


def volumes() -> dict[str, modal.Volume]:
    return {
        "/root/models": get_named_volume("SAPIA_MODAL_VOLUME_AF3_PARAMS", "sapia-af3-params"),
        "/root/public_databases": get_named_volume("SAPIA_MODAL_VOLUME_AF3_DB", "sapia-af3-db"),
    }
