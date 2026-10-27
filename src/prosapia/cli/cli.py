# PYTHON_ARGCOMPLETE_OK
"""The ``sapia`` console-script dispatcher.

Builds ONE argparse tree spanning every discovered tool
(``sapia {run,collect} <tool> [tool args...]``) so a single ``argcomplete`` call
completes verbs, tool names, and each tool's own flags. No ``sys.argv`` rewriting:
each tool subparser reuses the tool's ``build_run_parser`` / ``build_collect_parser``
as a parent and dispatches to ``run_tool`` / ``collect_tool``.

Enable shell completion once with:  ``sapia init``
"""

import os
from argparse import ArgumentParser
from pathlib import Path

import argcomplete

from .completion import build_init_parser, init_from_args
from ..core.base_collect import build_collect_parser
from ..core.base_run import build_run_parser
from ..core.tool import Tool, collect_tool, run_tool
from ..core.tool_registry import discover, BUILTIN_TOOLS_DIR
from .delete import build_delete_parser, delete_from_args
from .fork_tool import build_fork_parser, fork_from_args
from .merge import build_merge_parser, merge_from_args
from .modal_shell import build_modal_shell_parser, modal_shell_from_args
from .new_run_dir import build_new_run_parser, new_run_from_args


def tools_dirs() -> list[Path]:
    """Built-in tools first, then user dirs from $PROSAPIA_TOOLS_DIR
    (os.pathsep-separated). Later dirs win, so user tools shadow built-ins."""
    dirs = [BUILTIN_TOOLS_DIR]
    if env := os.environ.get("PROSAPIA_TOOLS_DIR", "tools"):
        dirs += [Path(p) for p in env.split(os.pathsep) if p]
    return dirs


def _build_parser(tools: dict[str, Tool]) -> ArgumentParser:
    top = ArgumentParser(prog="sapia", description="Protein-design pipeline CLI.")
    verbs = top.add_subparsers(dest="verb", required=True)

    new_run_p = verbs.add_parser(
        "new_run",
        parents=[build_new_run_parser()],
        help="Create a fresh run_dir for a workflow.",
    )
    new_run_p.set_defaults(_dispatch=new_run_from_args)

    init_p = verbs.add_parser(
        "init",
        parents=[build_init_parser()],
        help="Set up shell tab-completion, or scaffold starter config (--config).",
    )
    init_p.set_defaults(_dispatch=init_from_args)

    fork_p = verbs.add_parser(
        "fork-tool",
        parents=[build_fork_parser()],
        help="Copy a built-in tool into your tools dir to customize it.",
    )
    fork_p.set_defaults(_dispatch=fork_from_args)

    merge_p = verbs.add_parser(
        "merge",
        parents=[build_merge_parser()],
        help="Pool sibling tables (same parent) into one new child table.",
    )
    merge_p.set_defaults(_dispatch=merge_from_args)

    delete_p = verbs.add_parser(
        "delete",
        parents=[build_delete_parser()],
        help="Remove a tool run: its leaf dir and the columns (or table) it produced.",
    )
    delete_p.set_defaults(_dispatch=delete_from_args)

    modal_shell_p = verbs.add_parser(
        "modal-shell",
        parents=[build_modal_shell_parser()],
        help="Open a shell on Modal with the runs Volume mounted.",
    )
    modal_shell_p.set_defaults(_dispatch=modal_shell_from_args)

    run_tools = verbs.add_parser(
        "run", help="Submit a tool's tasks (SLURM array, Modal, or local)."
    ).add_subparsers(dest="tool", required=True)
    collect_tools = verbs.add_parser(
        "collect", help="Collect a tool's outputs into its table."
    ).add_subparsers(dest="tool", required=True)

    for name, tool in sorted(tools.items()):
        run_p = run_tools.add_parser(
            name,
            help=tool.description,
            description=tool.description,
            parents=[
                build_run_parser(
                    tool.metadata,
                    tool.default_script,
                    tool.default_input_column,
                    tool.add_run_args_fn,
                )
            ],
        )
        run_p.set_defaults(_dispatch=lambda args, t=tool: run_tool(t, args))

        collect_p = collect_tools.add_parser(
            name,
            help=tool.description,
            description=tool.description,
            parents=[
                build_collect_parser(
                    tool.add_collect_args_fn,
                )
            ],
        )
        collect_p.set_defaults(_dispatch=lambda args, t=tool: collect_tool(t, args))

    return top


def main() -> None:
    tools = discover(*tools_dirs())
    parser = _build_parser(tools)
    argcomplete.autocomplete(parser)
    args = parser.parse_args()
    args._dispatch(args)
