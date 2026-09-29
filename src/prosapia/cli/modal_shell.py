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
import base64
import subprocess
import sys
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


def modal_shell_argv(args: argparse.Namespace) -> list[str]:
    argv = [sys.executable, "-m", "modal", "shell", f"{WORKSTATION}::workstation"]
    if args.cmd:
        # Modal wraps --cmd as `bash -c "<cmd>"`, so any `"` in it would break out.
        # Base64 has no quotes; process substitution keeps the command's stdin.
        b64 = base64.b64encode(args.cmd.encode()).decode()
        argv += ["--cmd", f"bash <(echo {b64} | base64 -d)"]
    if args.cmd and not sys.stdin.isatty():
        argv.insert(4, "--no-pty")
    return argv


def modal_shell_from_args(args: argparse.Namespace) -> None:
    raise SystemExit(subprocess.run(modal_shell_argv(args)).returncode)
