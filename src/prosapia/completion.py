"""``sapia init`` -- set up shell tab-completion for the ``sapia`` CLI.

Completion is powered by ``argcomplete``. Rather than making users hand-copy a
``register-python-argcomplete`` line, ``sapia init`` injects the completion hook
into their shell rc file for them (idempotently, inside a marked block):

    sapia init                # auto-detect shell, write the block to your rc
    sapia init --shell zsh    # force a shell
    sapia init --print        # just emit the shellcode (for `eval "$(sapia init --print)"`)

After a plain ``sapia init`` you restart the shell (or ``source`` the rc) once and
``sapia run <TAB>`` completes verbs, tool names, and each tool's flags.
"""

import argparse
import os
from pathlib import Path

import argcomplete

_SUPPORTED = ("bash", "zsh")
_RC_FILE = {"bash": "~/.bashrc", "zsh": "~/.zshrc"}
_BEGIN = "# >>> sapia completion >>>"
_END = "# <<< sapia completion <<<"


def _detect_shell() -> str | None:
    """Best-effort shell name from ``$SHELL`` (basename), if supported."""
    shell = Path(os.environ.get("SHELL", "")).name
    return shell if shell in _SUPPORTED else None


def _shellcode(shell: str) -> str:
    """Static completion snippet argcomplete generates for the ``sapia`` command."""
    return argcomplete.shellcode(["sapia"], shell=shell)  # type: ignore


def _write_block(rc_path: Path, shell: str) -> bool:
    """Insert/replace the marked completion block in ``rc_path``.

    Returns True if the file changed, False if the block was already up to date.
    """
    block = f"{_BEGIN}\n{_shellcode(shell).strip()}\n{_END}\n"
    existing = rc_path.read_text() if rc_path.exists() else ""

    if _BEGIN in existing and _END in existing:
        head, _, rest = existing.partition(_BEGIN)
        _, _, tail = rest.partition(_END)
        updated = f"{head}{block}{tail.lstrip(chr(10))}"
    else:
        sep = "" if existing == "" or existing.endswith("\n") else "\n"
        updated = f"{existing}{sep}{block}"

    if updated == existing:
        return False
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    rc_path.write_text(updated)
    return True


def build_init_parser() -> argparse.ArgumentParser:
    """Parent parser for the ``init`` verb."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--shell",
        choices=_SUPPORTED,
        default=None,
        help="Target shell. Defaults to the shell named in $SHELL.",
    )
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="Print the completion shellcode instead of writing it to your rc file "
        '(for `eval "$(sapia init --print)"`).',
    )
    return parser


def init_from_args(args: argparse.Namespace) -> None:
    """Dispatch for ``sapia init``: emit shellcode or write it into the shell rc."""
    shell = args.shell or _detect_shell()
    if shell is None:
        raise SystemExit(
            "Could not detect your shell from $SHELL. Re-run with --shell "
            f"{{{','.join(_SUPPORTED)}}}."
        )

    if args.print_only:
        print(_shellcode(shell), end="")
        return

    rc_path = Path(_RC_FILE[shell]).expanduser()
    changed = _write_block(rc_path, shell)
    if changed:
        print(f"Wrote sapia completion for {shell} to {rc_path}.")
        print(f"Restart your shell or run:  source {rc_path}")
    else:
        print(f"sapia completion already up to date in {rc_path}.")
