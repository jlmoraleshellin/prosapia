import argparse
from pathlib import Path


def base_parser(require_database: bool = True) -> argparse.ArgumentParser:
    """Parent parser with arguments shared across all pipeline scripts.

    ``require_database`` defaults True (every collect/array tool needs a source
    db); a root tool (e.g. worms) passes False since it has no input db.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "-d",
        "--database",
        type=str,
        required=require_database,
        default=None,
        help="Name of the TSV database in run_dir (without extension)."
        + (" Required." if require_database else " Optional for a root tool."),
    )
    return parser
