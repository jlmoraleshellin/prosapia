"""Opt-in integer-expression evaluator with db-column resolution.

``resolve_expr`` evaluates a small whitelisted arithmetic language where bare
identifiers are resolved as database columns via a lineage ``lookup``. Tools use
it to let users write specs like ``hairpin_length - 1`` or ``{prebundle_length}``
whose values are inherited per-design from the db.

Only integers, bare column names, and ``+ - * //`` are allowed; calls,
attributes, and every other node type are rejected.
"""

import ast
import operator
import re

import pandas as pd

from .base_sbatch import LookupFn

# ``{expr}`` islands inside a template string; the inner expression is resolved
# per-design via resolve_expr and everything outside is left literal.
_PLACEHOLDER = re.compile(r"\{([^}]*)\}")

# Whitelisted binary operators for the safe evaluator.
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
}


def _resolve_column(column: str, lookup: LookupFn, name: str) -> int:
    """Resolve a bare column name to an int via lineage lookup."""
    val = lookup(name, column)
    if val is None or pd.isna(val):
        raise ValueError(
            f"design {name!r}: column {column!r} not found (or empty) in lineage"
        )
    f = float(val)
    if not f.is_integer():
        raise ValueError(
            f"design {name!r}: column {column!r}={val!r} is not an integer"
        )
    return int(f)


def _safe_eval(node: ast.AST, lookup: LookupFn, name: str, expr: str) -> int:
    """Evaluate a whitelisted integer-arithmetic AST.

    Bare identifiers are resolved as db columns via ``lookup``; calls, attributes
    and any other node type are rejected.
    """
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, lookup, name, expr)
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.Name):
        return _resolve_column(node.id, lookup, name)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](
            _safe_eval(node.left, lookup, name, expr),
            _safe_eval(node.right, lookup, name, expr),
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _safe_eval(node.operand, lookup, name, expr)
        return v if isinstance(node.op, ast.UAdd) else -v
    raise ValueError(
        f"design {name!r}: unsupported expression {expr!r} "
        f"(only integers, column names, and + - * // are allowed)"
    )


def resolve_expr(expr: str, lookup: LookupFn, name: str) -> int:
    """Evaluate an integer arithmetic expression, resolving bare names as db columns.

    ``expr`` may be an integer literal, a bare db column name (resolved up the
    lineage for ``name`` via ``lookup``), or any ``+ - * //`` combination thereof.
    """
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        raise ValueError(f"design {name!r}: could not parse expression {expr!r}")
    return _safe_eval(tree, lookup, name, expr)


def resolve_template(template: str, lookup: LookupFn, name: str) -> str:
    """Substitute every ``{expr}`` island in a template with its resolved integer.

    This is the shared, tool-agnostic expression layer: text outside braces is a
    tool's native/mini-language (RFdiffusion contigs, ProteinMPNN position lists,
    ...) and is left verbatim; each ``{expr}`` is resolved via ``resolve_expr``
    (integers, bare db column names, and ``+ - * //`` up the lineage for ``name``).
    """
    return _PLACEHOLDER.sub(
        lambda m: str(resolve_expr(m.group(1), lookup, name)), template
    )
