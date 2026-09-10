import argparse
from pathlib import Path


def base_parser(require_table: bool = True) -> argparse.ArgumentParser:
    """Parent parser with arguments shared across all pipeline scripts.

    ``require_table`` defaults True (every collect/array tool needs a source
    table); a create tool passes False since it may not need an input table.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "-t",
        "--table",
        type=str,
        required=require_table,
        default=None,
        help="Name of the TSV table in run_dir (without extension)."
        + (" Required." if require_table else " Optional for a create tool."),
    )
    return parser
