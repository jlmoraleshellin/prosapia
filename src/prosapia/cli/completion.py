"""``sapia init`` -- set up shell tab-completion for the ``sapia`` CLI.

Completion is powered by ``argcomplete``. ``sapia init`` installs the completion
hook for you. By default it drops an autoloaded completion file into your shell's
standard completion directory -- no rc edit, lazily loaded on first use, and zero
shell-startup cost:

    sapia init                 # auto-detect shell, install the completion file
    sapia init --shell zsh     # force a shell
    sapia init --rc            # instead, append a marked block to your shell rc
    sapia init --print         # just emit the shellcode (for `eval "$(sapia init --print)"`)

The default writes to (honoring ``$XDG_DATA_HOME``, default ``~/.local/share``):
    bash -> <data>/bash-completion/completions/sapia
    zsh  -> <data>/zsh/site-functions/_sapia

Bash autoloads it via the ``bash-completion`` package; zsh autoloads it from any
directory on ``$fpath``. Use ``--rc`` if you don't have ``bash-completion`` or
prefer everything in one rc file, or ``--print`` for an ephemeral, session-only
setup (``eval "$(sapia init --print)"``).
"""

import argparse
import os
from pathlib import Path

import argcomplete

_SUPPORTED = ("bash", "zsh")
_RC_FILE = {"bash": "~/.bashrc", "zsh": "~/.zshrc"}
# (completion-dir subpath under the user data dir, completion filename) per shell.
_COMPLETION_FILE = {
    "bash": ("bash-completion/completions", "sapia"),
    "zsh": ("zsh/site-functions", "_sapia"),
}
_BEGIN = "# >>> sapia completion >>>"
_END = "# <<< sapia completion <<<"


def _detect_shell() -> str | None:
    """Best-effort shell name from ``$SHELL`` (basename), if supported."""
    shell = Path(os.environ.get("SHELL", "")).name
    return shell if shell in _SUPPORTED else None


def _shellcode(shell: str) -> str:
    """Autoloadable completion script argcomplete generates for ``sapia``."""
    return argcomplete.shellcode(["sapia"], shell=shell)  # type: ignore


def _data_home() -> Path:
    """User data dir: ``$XDG_DATA_HOME`` if set, else ``~/.local/share``."""
    return Path(os.environ.get("XDG_DATA_HOME") or "~/.local/share").expanduser()


def _completion_path(shell: str) -> Path:
    """Standard per-shell completion-file destination.

    Honors ``$BASH_COMPLETION_USER_DIR`` for bash; otherwise sits under the user
    data dir (see :func:`_data_home`).
    """
    subdir, filename = _COMPLETION_FILE[shell]
    if shell == "bash" and (user_dir := os.environ.get("BASH_COMPLETION_USER_DIR")):
        return Path(user_dir).expanduser() / "completions" / filename
    return _data_home() / subdir / filename


def _write_text(path: Path, content: str) -> bool:
    """Write ``content`` to ``path`` if it differs. Returns True if it changed."""
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--rc",
        action="store_true",
        help="Append a marked completion block to your shell rc file instead of "
        "installing an autoloaded completion file (use if you lack bash-completion).",
    )
    mode.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="Print the completion shellcode instead of installing it "
        '(for a session-only setup: `eval "$(sapia init --print)"`).',
    )
    return parser


def _install_completion_file(shell: str) -> None:
    """Default install: drop an autoloaded completion file in the standard dir."""
    path = _completion_path(shell)
    changed = _write_text(path, _shellcode(shell))
    if changed:
        print(f"Wrote sapia {shell} completion to {path}.")
    else:
        print(f"sapia {shell} completion already up to date at {path}.")

    if shell == "bash":
        print("Restart your shell to use it (requires the 'bash-completion' package).")
    else:
        print("Restart your shell to use it. If completion doesn't kick in, make sure")
        print("that directory is on your fpath before compinit, e.g. in ~/.zshrc:")
        print(f"  fpath=({path.parent} $fpath)")


def _install_rc_block(shell: str) -> None:
    """Fallback install: splice a marked block into the shell rc file."""
    rc_path = Path(_RC_FILE[shell]).expanduser()
    changed = _write_block(rc_path, shell)
    if changed:
        print(f"Wrote sapia completion block for {shell} to {rc_path}.")
        print(f"Restart your shell or run:  source {rc_path}")
    else:
        print(f"sapia completion already up to date in {rc_path}.")


def init_from_args(args: argparse.Namespace) -> None:
    """Dispatch for ``sapia init``: print, write an rc block, or install a file."""
    shell = args.shell or _detect_shell()
    if shell is None:
        raise SystemExit(
            "Could not detect your shell from $SHELL. Re-run with --shell "
            f"{{{','.join(_SUPPORTED)}}}."
        )

    if args.print_only:
        print(_shellcode(shell), end="")
    elif args.rc:
        _install_rc_block(shell)
    else:
        _install_completion_file(shell)
