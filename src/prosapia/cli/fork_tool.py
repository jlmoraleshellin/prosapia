"""``sapia fork-tool`` -- copy a bundled tool into your tools dir to customize it.

Prosapia ships general-purpose tools (rfdiffusion, proteinmpnn, ...). When a
bundled tool is close but not quite right, the surest way to adapt it is to start
from a working copy rather than a blank file. This verb copies a built-in tool's
whole folder into your tools dir; you then edit the copy.

    sapia fork-tool rfdiffusion              # -> ./tools/rfdiffusion/
    sapia fork-tool rfdiffusion my_rfdiff    # -> ./tools/my_rfdiff/
    sapia fork-tool rfdiffusion --tools-dir path/to/tools

Discovery keys on the ``name`` in ``spec.py``, not the folder name, so:
  - keep ``name="rfdiffusion"`` to SHADOW the built-in (``sapia run rfdiffusion``
    now uses your copy -- user dirs win over built-ins);
  - change ``name`` to register a NEW tool alongside the built-in.

The destination tools dir must be on ``$PROSAPIA_TOOLS_DIR`` for ``sapia`` to find
the copy (the default, ``./tools``, already is). See also ``Tool.with_overrides``
for reusing a bundled tool without copying its files.
"""

import argparse
import os
import shutil
from pathlib import Path

from ..core.tool_registry import BUILTIN_TOOLS_DIR, _load


def _builtin_folders() -> dict[str, Path]:
    """Map each built-in tool's ``name`` to its source folder.

    The registry keys tools by ``Tool.name``, which may differ from the folder
    name (e.g. ``mpnn_seqs`` lives in ``proteinmpnn/``), so we load each spec to
    read its name.
    """
    folders: dict[str, Path] = {}
    for spec in sorted(BUILTIN_TOOLS_DIR.glob("*/spec.py")):
        folders[_load(spec).name] = spec.parent
    return folders


def _default_tools_dir() -> Path:
    """First entry of ``$PROSAPIA_TOOLS_DIR`` (built-ins excluded), else ``tools``."""
    env = os.environ.get("PROSAPIA_TOOLS_DIR", "tools")
    first = next((p for p in env.split(os.pathsep) if p), "tools")
    return Path(first)


def build_fork_parser() -> argparse.ArgumentParser:
    """Parent parser for the ``fork-tool`` verb."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "tool",
        help="Name of the built-in tool to copy (as it appears in `sapia run <tool>`).",
    )
    parser.add_argument(
        "dest",
        nargs="?",
        default=None,
        help="Destination folder name under the tools dir. "
        "Defaults to the built-in's folder name.",
    )
    parser.add_argument(
        "--tools-dir",
        type=Path,
        default=None,
        help="Destination tools dir. Defaults to the first entry of "
        "$PROSAPIA_TOOLS_DIR (or './tools').",
    )
    return parser


def fork_from_args(args: argparse.Namespace) -> None:
    """Dispatch for ``sapia fork-tool``: copy a built-in tool folder into the tools dir."""
    folders = _builtin_folders()
    if args.tool not in folders:
        available = ", ".join(sorted(folders))
        raise SystemExit(
            f"Unknown built-in tool {args.tool!r}. Available: {available}."
        )

    src = folders[args.tool]
    dest_base = args.tools_dir or _default_tools_dir()
    dest = dest_base / (args.dest or src.name)

    if dest.exists():
        raise SystemExit(
            f"Destination {dest} already exists; pass a different name or remove it."
        )

    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    print(f"Copied built-in tool {args.tool!r} to {dest}")
    print("Next steps:")
    print(f"  - Edit {dest}/spec.py and its run_*/collect_* modules to customize it.")
    print(f"  - Make sure {dest_base} is on $PROSAPIA_TOOLS_DIR (default './tools').")
    print(
        f'  - Keep name="{args.tool}" in spec.py to shadow the built-in, '
        "or change it to register a new tool alongside it."
    )
