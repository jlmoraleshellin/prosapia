"""
Create a fresh ``run_dir`` -- the container every pipeline tool operates inside.

A ``run_dir`` holds a workflow's databases (``*.tsv`` + ``_registry.tsv``) and the
tools' nested output dirs (``run_dir/<db>/<tool>/``). Creating one is deliberately
*decoupled* from any tool: a tool receives an existing ``run_dir``, it never mints
one. Run this first, then hand the printed path to the root tool (worms) and
everything downstream.

The created path is printed to stdout (and only that), so it can be captured:

    RUN_DIR=$(sapia new_run --label grow_hairpin)

Usage:
    sapia new_run
    sapia new_run --label grow_hairpin
    sapia new_run --label grow_hairpin --base runs
"""

import argparse
from datetime import datetime
from pathlib import Path


def new_run_dir(base: str = "outputs", label: str = "") -> Path:
    """Create and return a timestamped run dir ``<base>/<timestamp>[_<label>]``."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{timestamp}_{label}" if label else timestamp
    run_dir = Path(base) / name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def build_new_run_parser() -> argparse.ArgumentParser:
    """Parent parser for the ``new_run`` verb (``--label`` / ``--base``)."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--label",
        type=str,
        default="",
        help="Label appended to the timestamped run directory name.",
    )
    parser.add_argument(
        "--base",
        type=str,
        default="outputs",
        help="Parent directory for the timestamped run directory. Defaults to 'outputs'.",
    )
    return parser


def new_run_from_args(args: argparse.Namespace) -> None:
    """Dispatch for ``sapia new_run``: create the dir and print its path."""
    run_dir = new_run_dir(base=args.base, label=args.label)
    # Sole stdout line: the path, so it can be captured by command substitution.
    print(run_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a fresh run_dir for a pipeline workflow.",
        parents=[build_new_run_parser()],
    )
    new_run_from_args(parser.parse_args())


if __name__ == "__main__":
    main()
