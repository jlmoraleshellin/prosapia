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
import sys
from pathlib import Path

import modal
from dotenv import load_dotenv

from prosapia.cli.cli import tools_dirs
from prosapia.core.executors import RUNS_MOUNT
from prosapia.core.executors.modal import (
    DOTENV_ENV,
    get_dotenv_vars,
    get_runs_volume,
)

REMOTE_DOTENV = "/root/sapia.env"
# The local Python, so the workstation resolves the same dependency set.
PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"
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


app = modal.App("sapia-workstation")

workstation_function = app.function(
    image=_image(),
    volumes={RUNS_MOUNT: get_runs_volume()},
    secrets=[modal.Secret.from_dict(get_dotenv_vars())],
    cpu=float(os.environ.get("SAPIA_MODAL_SHELL_CPU", 0.25)),
    memory=int(os.environ.get("SAPIA_MODAL_SHELL_MEMORY", 1024)),
    timeout=24 * 3600,
)


@workstation_function
def workstation() -> None:
    """Spec for ``modal shell``; never called."""


@workstation_function
def shell() -> int:
    """Interactive shell, in a *function* container rather than a Sandbox.

    ``modal.interact()`` asks the server for a PTY and wires it to the local terminal;
    it only works when the app was started with ``interactive=True``. Running the shell
    here rather than through ``modal shell`` is what lets a submit typed inside it flush
    the Volume with one commit, which a Sandbox may not do.
    """
    import subprocess

    modal.interact()
    return subprocess.run(["bash", "-l"], cwd=RUNS_MOUNT).returncode


@workstation_function
def run_cmd(cmd: str) -> int:
    """Run one command in the workstation, as a *function* container.

    ``modal shell`` gives a Sandbox, and the server refuses ``Volume.commit()`` from
    one. A function container may commit, which lets a submit inside it flush
    everything it staged with a single call instead of uploading the staged files one
    by one -- the difference between one request and ten thousand on a large run.
    """
    import subprocess

    return subprocess.run(["bash", "-lc", cmd], cwd=RUNS_MOUNT).returncode
