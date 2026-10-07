"""
Open the Modal workstation: a shell in a small prosapia container with the runs
Volume mounted at ``/runs`` (also its cwd), so run_dirs live only on the Volume.
Inside it, ``sapia`` works as usual and ``run`` defaults to the modal executor.
Needs ``prosapia[modal]`` and the Modal settings in the local ``.env``.

Usage:
    sapia modal-shell                                   # interactive shell
    sapia modal-shell --cmd "sapia new_run --label x"   # one command, then exit
"""

import argparse
from pathlib import Path

WORKSTATION = Path(__file__).parent.parent / "core" / "executors" / "workstation.py"


def build_modal_shell_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "-c",
        "--cmd",
        type=str,
        default=None,
        help="Run this command in the workstation and exit instead of opening a shell.",
    )
    return parser


def _load_workstation():
    """Import the workstation module by path, the way the modal CLI used to."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("sapia_workstation", WORKSTATION)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load the workstation from {WORKSTATION}")
    workstation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workstation)
    return workstation


def modal_shell_from_args(args: argparse.Namespace) -> None:
    """Open the workstation, or run one command in it, as a *function* container.

    Not ``modal shell``: that gives a Sandbox, and the server refuses
    ``Volume.commit()`` from one, which would force the submit path to upload every
    staged file instead of flushing them all at once.

    ``enable_output`` is required twice over: without it modal swallows the container's
    stdout, and interactive mode refuses to start without progress output.
    """
    import sys

    import modal

    if not args.cmd and not sys.stdin.isatty():
        raise SystemExit(
            "sapia modal-shell needs a terminal. Without one, modal has no PTY to "
            "attach and the shell would hang; use --cmd to run a single command."
        )

    workstation = _load_workstation()
    with modal.enable_output(), workstation.app.run(interactive=not args.cmd):
        if args.cmd:
            raise SystemExit(workstation.run_cmd.remote(args.cmd))
        raise SystemExit(workstation.shell.remote())
