"""Tests for ``sapia merge``: pooling sibling tables into one child table."""

import json
from argparse import Namespace

import pandas as pd
import pytest

from prosapia.cli.merge import merge_from_args, name_suffix
from prosapia.core import GEN, PARENT_NAME, PARENT_TABLE, ROOT_PARENT, Table, DataManager
from prosapia.core.naming import RUN_META_FILENAME


def _write(dm: DataManager, table: Table, rows: dict[str, dict]) -> None:
    dm.rm.register_table(table)
    df = dm.read_frame(table.table_name)
    for name, data in rows.items():
        df = dm.update(df, name, data)
    dm.write_frame(table.table_name, df)


def _child_row(parent_name: str, parent_table: str, gen: int, **extra) -> dict:
    return {PARENT_NAME: parent_name, PARENT_TABLE: parent_table, GEN: gen, **extra}


def _siblings(tmp_path):
    """A labelled root with two labelled children (gen 1) sharing design S0."""
    dm = DataManager(tmp_path)
    root = Table("table0_worms", 0, "worms", None, "seed")
    _write(dm, root, {"S0": {"n_subunits": 11}})
    a = Table("table1_worms_a", 1, "worms_a", "table0_worms", "mpnn")
    b = Table("table1_worms_b", 1, "worms_b", "table0_worms", "mpnn")
    _write(
        dm,
        a,
        {"S0_f0": _child_row("S0", "table0_worms", 1, sequence="AAA", score_a=1.0)},
    )
    _write(
        dm,
        b,
        {"S0_f0": _child_row("S0", "table0_worms", 1, sequence="BBB", score_b=2.0)},
    )
    return dm


def _merge(tmp_path, *tables, label="merged"):
    merge_from_args(Namespace(run_dir=tmp_path, tables=list(tables), table_label=label))


def test_name_suffix_strips_parent_label():
    assert name_suffix(Table("t", 1, "worms_a"), "worms") == "a"
    assert name_suffix(Table("t", 0, "x"), "") == "x"
    assert name_suffix(Table("t", 1, ""), "worms") == ""
    assert name_suffix(Table("t", 1, "other"), "worms") == "other"


def test_merge_siblings(tmp_path, capsys):
    dm = _siblings(tmp_path)
    capsys.readouterr()  # drop the backend's "table is new" lines from setup
    _merge(tmp_path, "table1_worms_a", "table1_worms_b")

    assert capsys.readouterr().out.strip() == "table1_worms_merged"

    df = dm.read_frame("table1_worms_merged")
    assert list(df.index) == ["S0_f0_a", "S0_f0_b"]
    assert df.at["S0_f0_a", "score_a"] == 1.0
    assert pd.isna(df.at["S0_f0_a", "score_b"])
    assert df.at["S0_f0_b", "score_b"] == 2.0
    assert (df[PARENT_NAME] == "S0").all()
    assert (df[PARENT_TABLE] == "table0_worms").all()
    assert (df[GEN] == 1).all()

    merged = dm.rm.get_table("table1_worms_merged")
    assert merged.parent_table_name == "table0_worms"
    assert merged.gen == 1
    assert merged.tool_name == "merge"

    meta = json.loads(
        (tmp_path / "table1_worms_merged" / "merge" / RUN_META_FILENAME).read_text()
    )
    assert meta["sources"] == ["table1_worms_a", "table1_worms_b"]
    assert meta["suffixes"] == {"table1_worms_a": "a", "table1_worms_b": "b"}

    # Sources untouched.
    assert list(dm.read_frame("table1_worms_a").index) == ["S0_f0"]


def test_merged_rows_resolve_lineage(tmp_path):
    dm = _siblings(tmp_path)
    _merge(tmp_path, "table1_worms_a", "table1_worms_b")
    df = dm.read_frame("table1_worms_merged")
    assert dm.lookup(df, "S0_f0_b", "n_subunits") == 11
    assert dm.trace_lineage("table1_worms_merged", "S0_f0_a") == [("table0_worms", "S0")]
    joined = dm.join_lineage("table1_worms_merged")
    assert joined.at["S0_f0_a", "n_subunits"] == 11


def test_merge_roots(tmp_path):
    dm = DataManager(tmp_path)
    _write(dm, Table("table0_x", 0, "x", None, "seed"), {"D0": {"v": 1}})
    _write(dm, Table("table0_y", 0, "y", None, "seed"), {"D0": {"v": 2}})
    _merge(tmp_path, "table0_x", "table0_y", label="pooled")

    df = dm.read_frame("table0_pooled")
    assert list(df.index) == ["D0_x", "D0_y"]
    reg = dm.rm.get_registry()
    assert reg.at["table0_pooled", PARENT_TABLE] == ROOT_PARENT
    assert int(reg.at["table0_pooled", GEN]) == 0


def test_unlabelled_source_keeps_bare_names(tmp_path):
    dm = DataManager(tmp_path)
    _write(dm, Table("table0", 0, "", None, "seed"), {"S0": {}})
    _write(dm, Table("table1", 1, "", "table0", "mpnn"), {"S0_f0": _child_row("S0", "table0", 1)})
    _write(dm, Table("table1_b", 1, "b", "table0", "mpnn"), {"S0_f0": _child_row("S0", "table0", 1)})
    _merge(tmp_path, "table1", "table1_b")
    assert list(dm.read_frame("table1_merged").index) == ["S0_f0", "S0_f0_b"]


def test_refuses_different_parents(tmp_path):
    dm = DataManager(tmp_path)
    _write(dm, Table("table0_x", 0, "x", None, "seed"), {"S0": {}})
    _write(dm, Table("table0_y", 0, "y", None, "seed"), {"S0": {}})
    _write(dm, Table("table1_x", 1, "x", "table0_x", "mpnn"), {"S0_f0": _child_row("S0", "table0_x", 1)})
    _write(dm, Table("table1_y", 1, "y", "table0_y", "mpnn"), {"S0_f0": _child_row("S0", "table0_y", 1)})
    with pytest.raises(SystemExit, match="same parent"):
        _merge(tmp_path, "table1_x", "table1_y")


def test_refuses_name_collision(tmp_path):
    dm = DataManager(tmp_path)
    _write(dm, Table("table0", 0, "", None, "seed"), {"S0": {}})
    # Suffix "b" applied to "S0_f0" in table1 collides with a pre-suffixed name.
    _write(dm, Table("table1", 1, "", "table0", "mpnn"), {"S0_f0_b": _child_row("S0", "table0", 1)})
    _write(dm, Table("table1_b", 1, "b", "table0", "mpnn"), {"S0_f0": _child_row("S0", "table0", 1)})
    with pytest.raises(SystemExit, match="collide.*S0_f0_b"):
        _merge(tmp_path, "table1", "table1_b")


def test_refuses_existing_target_and_unregistered(tmp_path):
    _siblings(tmp_path)
    _merge(tmp_path, "table1_worms_a", "table1_worms_b")
    with pytest.raises(SystemExit, match="already exists"):
        _merge(tmp_path, "table1_worms_a", "table1_worms_b")
    with pytest.raises(SystemExit, match="not in registry"):
        _merge(tmp_path, "table1_worms_a", "nope")
    with pytest.raises(SystemExit, match="at least two"):
        _merge(tmp_path, "table1_worms_a", "table1_worms_a")
