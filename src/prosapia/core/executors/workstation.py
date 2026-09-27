"""Modal workstation: a small prosapia container with the runs Volume mounted.

Opened with ``sapia modal-shell`` (``modal shell <this file>::workstation``), which
reuses the ``workstation`` function's image, volumes and secrets. Inside it ``sapia``
runs unchanged against run_dirs on the Volume (cwd is the mount), and
``sapia run ... --executor modal`` fans tasks out to the tools' own images. Nothing
is stored on the local machine.

This file is loaded by the ``modal`` CLI from the directory ``sapia modal-shell`` is
run in, so the local ``.env`` (runs volume, mount, per-tool settings) is read here.
"""

import importlib.metadata
import os
from pathlib import Path

import modal
from dotenv import load_dotenv

from prosapia.cli.cli import tools_dirs
from prosapia.core.executors import RUNS_MOUNT
from prosapia.core.executors.modal import (
    DOTENV_ENV,
    PYTHON_VERSION,
    get_dotenv_vars,
    get_runs_volume,
)

TOKEN_SECRET_ENV = "SAPIA_MODAL_TOKEN_SECRET"
REMOTE_DOTENV = "/root/sapia.env"
# `sapia` without installing the package: prosapia is shipped as source. Written by
# printf, so the \n escapes stay literal here.
SAPIA_LAUNCHER = '#!/bin/sh\\nexec python -c "from prosapia.cli.cli import main; main()" "$@"\\n'

load_dotenv(".env")


def _dependencies() -> list[str]:
    """prosapia's runtime requirements (no extras) plus the local modal client."""
    requires = importlib.metadata.requires("prosapia") or []
    return [r for r in requires if "extra ==" not in r] + [
        f"modal=={importlib.metadata.version('modal')}"
    ]


def _image() -> modal.Image:
    user_tool_dirs = [d.resolve() for d in tools_dirs()[1:] if d.is_dir()]
    env = {
        "PROSAPIA_TOOLS_DIR": os.pathsep.join(str(d) for d in user_tool_dirs),
        "SAPIA_EXECUTOR": "modal",
    }
    has_dotenv = Path(".env").is_file()
    if has_dotenv:
        env[DOTENV_ENV] = REMOTE_DOTENV

    image = (
        modal.Image.debian_slim(python_version=PYTHON_VERSION)
        .uv_pip_install(*_dependencies())
        .run_commands(
            f"printf '{SAPIA_LAUNCHER}' > /usr/local/bin/sapia",
            "chmod +x /usr/local/bin/sapia",
        )
        .env(env)
        .workdir(RUNS_MOUNT)
        # Whole package, not just .py: the prelude, tools' .sh and templates too.
        .add_local_python_source("prosapia", ignore=["**/__pycache__/**"])
    )
    for d in user_tool_dirs:
        image = image.add_local_dir(d, remote_path=str(d))
    if has_dotenv:
        image = image.add_local_file(".env", remote_path=REMOTE_DOTENV)
    return image


def _secrets() -> list[modal.Secret]:
    secrets = [modal.Secret.from_dict(get_dotenv_vars())]
    # Only needed if the container's own credentials can't launch the task apps.
    if name := os.environ.get(TOKEN_SECRET_ENV):
        secrets.append(modal.Secret.from_name(name))
    return secrets


app = modal.App("sapia-workstation")


@app.function(
    image=_image(),
    volumes={RUNS_MOUNT: get_runs_volume()},
    secrets=_secrets(),
    cpu=float(os.environ.get("SAPIA_MODAL_SHELL_CPU", 0.25)),
    memory=int(os.environ.get("SAPIA_MODAL_SHELL_MEMORY", 1024)),
    timeout=24 * 3600,
)
def workstation() -> None:
    """Spec for ``modal shell``; never called."""
