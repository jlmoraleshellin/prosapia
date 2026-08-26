"""Tests for pipeline_core.resolve_expr (integer arithmetic + db-column resolution)."""

import pytest

from prosapia.core import resolve_expr, resolve_template

# Stub lineage lookup: (name, column) -> value.
_COLUMNS = {"hairpin_length": 30, "prebundle_length": 12, "frac": 2.5, "empty": None}


def _lookup(name, column):
    return _COLUMNS.get(column)


def test_integer_literal():
    assert resolve_expr("5", _lookup, "d") == 5


def test_bare_column():
    assert resolve_expr("hairpin_length", _lookup, "d") == 30


def test_arithmetic_and_precedence():
    assert resolve_expr("hairpin_length - 1", _lookup, "d") == 29
    assert resolve_expr("2 + 3 * 4", _lookup, "d") == 14
    assert resolve_expr("prebundle_length // 5", _lookup, "d") == 2
    assert resolve_expr("-3", _lookup, "d") == -3


@pytest.mark.parametrize("expr", ["foo()", "os.system", "1.5", "a and b", "1 == 1"])
def test_rejects_non_whitelisted(expr):
    with pytest.raises(ValueError):
        resolve_expr(expr, _lookup, "d")


def test_missing_column_raises():
    with pytest.raises(ValueError):
        resolve_expr("does_not_exist", _lookup, "d")


def test_non_integer_column_raises():
    with pytest.raises(ValueError):
        resolve_expr("frac", _lookup, "d")


def test_empty_column_raises():
    with pytest.raises(ValueError):
        resolve_expr("empty", _lookup, "d")


def test_template_resolves_only_braced_islands():
    # RFdiffusion contig: braces carve expressions out of native syntax; the
    # chain letters, '/', '-' outside braces are left verbatim.
    assert (
        resolve_template("[20/A1-{prebundle_length}/0]", _lookup, "d") == "[20/A1-12/0]"
    )
    # ProteinMPNN position list: same mechanism, different surrounding grammar.
    assert resolve_template("24:{hairpin_length - 1}/10", _lookup, "d") == "24:29/10"


def test_template_without_braces_is_passthrough():
    assert (
        resolve_template("9:23/10,11,18:20,22", _lookup, "d") == "9:23/10,11,18:20,22"
    )


def test_template_bad_island_raises():
    with pytest.raises(ValueError):
        resolve_template("A1-{does_not_exist}/0", _lookup, "d")
