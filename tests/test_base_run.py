"""Tests for the run driver's row selection (``--where``)."""

import pandas as pd
import pytest

from prosapia.core.base_run import apply_where


def _df():
    return pd.DataFrame(
        {"merge_source": ["a", "a", "b"], "n": [1, 2, 2]},
        index=pd.Index(["r1", "r2", "r3"], name="name"),
    )


def test_single_clause():
    assert list(apply_where(_df(), ["merge_source=a"]).index) == ["r1", "r2"]


def test_clauses_combine_with_and():
    assert list(apply_where(_df(), ["merge_source=a", "n=2"]).index) == ["r2"]


def test_values_compared_as_strings():
    assert list(apply_where(_df(), ["n=2"]).index) == ["r2", "r3"]


def test_missing_column_raises():
    with pytest.raises(KeyError, match="nope"):
        apply_where(_df(), ["nope=1"])


def test_bad_clause_raises():
    with pytest.raises(ValueError, match="COL=VALUE"):
        apply_where(_df(), ["merge_source"])
