"""Tests for ``sapia merge``: pooling sibling tables into one child table."""

import json

import pandas as pd
import pytest

from prosapia.cli.merge import MergeArgs, merge_from_args, own_label
from prosapia.core import (
    GEN,
    MERGE_SOURCE,
    PARENT_NAME,
    PARENT_TABLE,
    ROOT_PARENT,
    Table,
    DataManager,
)
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


def _merge(tmp_path, *tables, label="merged", lift=False):
    merge_from_args(
        MergeArgs(run_dir=tmp_path, tables=list(tables), table_label=label, lift=lift)
    )


def test_own_label():
    assert own_label(Table("t", 1, "worms_a"), "worms") == "a"
    assert own_label(Table("t", 0, "x"), "") == "x"
    assert own_label(Table("t", 1, ""), "") == ""
    assert own_label(Table("t", 1, "worms"), "worms") == ""  # unlabelled child
    assert own_label(Table("t", 1, "low_T"), "worms") == "low_T"  # never split on _


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
    assert list(df[MERGE_SOURCE]) == ["table1_worms_a", "table1_worms_b"]

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
    assert list(df[MERGE_SOURCE]) == ["table0_x", "table0_y"]
    reg = dm.rm.get_registry()
    assert reg.at["table0_pooled", PARENT_TABLE] == ROOT_PARENT
    assert int(reg.at["table0_pooled", GEN]) == 0 # type: ignore


def test_unlabelled_source_keeps_bare_names(tmp_path):
    dm = DataManager(tmp_path)
    _write(dm, Table("table0", 0, "", None, "seed"), {"S0": {}})
    _write(dm, Table("table1", 1, "", "table0", "mpnn"), {"S0_f0": _child_row("S0", "table0", 1)})
    _write(dm, Table("table1_b", 1, "b", "table0", "mpnn"), {"S0_f0": _child_row("S0", "table0", 1)})
    _merge(tmp_path, "table1", "table1_b")
    assert list(dm.read_frame("table1_merged").index) == ["S0_f0", "S0_f0_b"]


def _cousins(tmp_path):
    """Root table0_x -> forks table1_x_a / table1_x_b -> one gen-2 child each."""
    dm = DataManager(tmp_path)
    _write(dm, Table("table0_x", 0, "x", None, "seed"), {"S0": {"n_subunits": 11}})
    for f in ("a", "b"):
        _write(
            dm,
            Table(f"table1_x_{f}", 1, f"x_{f}", "table0_x", "mpnn"),
            {"S0_f0": _child_row("S0", "table0_x", 1, sequence=f"{f}AA")},
        )
        _write(
            dm,
            Table(f"table2_x_{f}", 2, f"x_{f}", f"table1_x_{f}", "mpnn2"),
            {"S0_f0_d0": _child_row("S0_f0", f"table1_x_{f}", 2, score=len(f))},
        )
    return dm


def test_merge_cousins_builds_ghost_parent(tmp_path):
    dm = _cousins(tmp_path)
    _merge(tmp_path, "table2_x_a", "table2_x_b")

    ghost = dm.read_frame("table1_x_merged")
    assert list(ghost.index) == ["S0_f0_a", "S0_f0_b"]
    assert (ghost[PARENT_TABLE] == "table0_x").all()
    assert list(ghost[MERGE_SOURCE]) == ["table1_x_a", "table1_x_b"]

    df = dm.read_frame("table2_x_merged")
    assert list(df.index) == ["S0_f0_d0_a", "S0_f0_d0_b"]
    assert (df[PARENT_TABLE] == "table1_x_merged").all()
    assert list(df[PARENT_NAME]) == ["S0_f0_a", "S0_f0_b"]
    assert (df[GEN] == 2).all()

    reg = dm.rm
    assert reg.get_table("table2_x_merged").parent_table_name == "table1_x_merged"
    assert reg.get_table("table1_x_merged").parent_table_name == "table0_x"
    assert reg.get_table("table1_x_merged").tool_name == "merge"

    # Row lineage walks through the ghost copy to the real root.
    assert dm.trace_lineage("table2_x_merged", "S0_f0_d0_b") == [
        ("table1_x_merged", "S0_f0_b"),
        ("table0_x", "S0"),
    ]
    assert dm.lookup(df, "S0_f0_d0_b", "sequence") == "bAA"
    assert dm.lookup(df, "S0_f0_d0_a", "n_subunits") == 11

    meta = json.loads(
        (tmp_path / "table1_x_merged" / "merge" / RUN_META_FILENAME).read_text()
    )
    assert meta["sources"] == ["table1_x_a", "table1_x_b"]


def test_merge_cousins_reuses_existing_parent_merge(tmp_path, capsys):
    dm = _cousins(tmp_path)
    _merge(tmp_path, "table1_x_a", "table1_x_b")  # parents pooled first
    ghost_before = dm.read_frame("table1_x_merged")
    capsys.readouterr()
    _merge(tmp_path, "table2_x_a", "table2_x_b")
    assert capsys.readouterr().out.strip() == "table2_x_merged"
    pd.testing.assert_frame_equal(dm.read_frame("table1_x_merged"), ghost_before)
    df = dm.read_frame("table2_x_merged")
    assert dm.lookup(df, "S0_f0_d0_a", "sequence") == "aAA"


def test_refuses_existing_name_with_other_sources(tmp_path):
    dm = _cousins(tmp_path)
    # Occupy the ghost's name with an unrelated table.
    _write(dm, Table("table1_x_merged", 1, "x_merged", "table0_x", "mpnn"), {"Z": {}})
    with pytest.raises(SystemExit, match="not a merge of"):
        _merge(tmp_path, "table2_x_a", "table2_x_b")


def test_second_cousins_across_roots(tmp_path):
    dm = DataManager(tmp_path)
    for r in ("x", "y"):
        _write(dm, Table(f"table0_{r}", 0, r, None, "seed"), {"S0": {"v": 1}})
        _write(
            dm,
            Table(f"table1_{r}", 1, r, f"table0_{r}", "mpnn"),
            {"S0_f0": _child_row("S0", f"table0_{r}", 1)},
        )
        _write(
            dm,
            Table(f"table2_{r}", 2, r, f"table1_{r}", "mpnn2"),
            {"S0_f0_d0": _child_row("S0_f0", f"table1_{r}", 2)},
        )
    _merge(tmp_path, "table2_x", "table2_y")
    assert list(dm.read_frame("table0_merged").index) == ["S0_x", "S0_y"]
    assert list(dm.read_frame("table1_merged").index) == ["S0_f0_x", "S0_f0_y"]
    df = dm.read_frame("table2_merged")
    assert list(df.index) == ["S0_f0_d0_x", "S0_f0_d0_y"]
    assert dm.trace_lineage("table2_merged", "S0_f0_d0_y") == [
        ("table1_merged", "S0_f0_y"),
        ("table0_merged", "S0_y"),
    ]


def test_refuses_different_gens(tmp_path):
    _cousins(tmp_path)
    with pytest.raises(SystemExit, match="same gen"):
        _merge(tmp_path, "table1_x_a", "table2_x_b")


def test_refuses_name_collision(tmp_path):
    dm = DataManager(tmp_path)
    _write(dm, Table("table0", 0, "", None, "seed"), {"S0": {}})
    # Suffix "b" applied to "S0_f0" in table1 collides with a pre-suffixed name.
    _write(dm, Table("table1", 1, "", "table0", "mpnn"), {"S0_f0_b": _child_row("S0", "table0", 1)})
    _write(dm, Table("table1_b", 1, "b", "table0", "mpnn"), {"S0_f0": _child_row("S0", "table0", 1)})
    with pytest.raises(SystemExit, match="collide.*S0_f0_b"):
        _merge(tmp_path, "table1", "table1_b")


def test_rerun_reuses_and_refuses_unregistered(tmp_path, capsys):
    dm = _siblings(tmp_path)
    _merge(tmp_path, "table1_worms_a", "table1_worms_b")
    before = dm.read_frame("table1_worms_merged")
    capsys.readouterr()
    _merge(tmp_path, "table1_worms_a", "table1_worms_b")  # same sources: reused
    assert capsys.readouterr().out.strip() == "table1_worms_merged"
    pd.testing.assert_frame_equal(dm.read_frame("table1_worms_merged"), before)
    with pytest.raises(SystemExit, match="not in registry"):
        _merge(tmp_path, "table1_worms_a", "nope")
    with pytest.raises(SystemExit, match="at least two"):
        _merge(tmp_path, "table1_worms_a", "table1_worms_a")


def _gen_gap(tmp_path):
    """table0_x -> table1_x -> forks table2_x_a / table2_x_b; only fork a took
    one more step (table3_x_a)."""
    dm = DataManager(tmp_path)
    _write(dm, Table("table0_x", 0, "x", None, "seed"), {"S0": {"n_subunits": 11}})
    _write(dm, Table("table1_x", 1, "x", "table0_x", "mpnn"), {"S0_f0": _child_row("S0", "table0_x", 1)})
    for f in ("a", "b"):
        _write(
            dm,
            Table(f"table2_x_{f}", 2, f"x_{f}", "table1_x", "mpnn2"),
            {"S0_f0_d0": _child_row("S0_f0", "table1_x", 2, boltz_path=f"{f}.cif")},
        )
    _write(
        dm,
        Table("table3_x_a", 3, "x_a", "table2_x_a", "relax"),
        {"S0_f0_d0_r0": _child_row("S0_f0_d0", "table2_x_a", 3, boltz_path="a_relaxed.cif")},
    )
    return dm


def test_gen_gap_refused_without_lift(tmp_path):
    _gen_gap(tmp_path)
    with pytest.raises(SystemExit, match="same gen.*--lift"):
        _merge(tmp_path, "table3_x_a", "table2_x_b")


def test_lift_pads_shallow_lineage(tmp_path):
    dm = _gen_gap(tmp_path)
    _merge(tmp_path, "table3_x_a", "table2_x_b", lift=True)

    ghost = dm.read_frame("table2_x_merged")
    assert list(ghost.index) == ["S0_f0_d0_a", "S0_f0_d0_b"]
    assert (ghost[PARENT_TABLE] == "table1_x").all()

    df = dm.read_frame("table3_x_merged")
    assert list(df.index) == ["S0_f0_d0_r0_a", "S0_f0_d0_b"]
    assert list(df[PARENT_NAME]) == ["S0_f0_d0_a", "S0_f0_d0_b"]  # lifted row -> own copy
    assert (df[PARENT_TABLE] == "table2_x_merged").all()
    assert list(df[GEN]) == [3, 3]
    assert list(df[MERGE_SOURCE]) == ["table3_x_a", "table2_x_b"]
    assert list(df["boltz_path"]) == ["a_relaxed.cif", "b.cif"]

    assert dm.rm.get_table("table3_x_merged").parent_table_name == "table2_x_merged"
    assert dm.trace_lineage("table3_x_merged", "S0_f0_d0_b") == [
        ("table2_x_merged", "S0_f0_d0_b"),
        ("table1_x", "S0_f0"),
        ("table0_x", "S0"),
    ]
    assert dm.lookup(df, "S0_f0_d0_b", "n_subunits") == 11


def test_lift_from_own_parent_needs_no_ghost(tmp_path):
    dm = _gen_gap(tmp_path)
    _merge(tmp_path, "table2_x_b", "table1_x", lift=True)
    df = dm.read_frame("table2_x_merged")
    assert list(df.index) == ["S0_f0_d0_b", "S0_f0"]
    assert list(df[PARENT_TABLE]) == ["table1_x", "table1_x"]
    assert list(df[PARENT_NAME]) == ["S0_f0", "S0_f0"]
    assert dm.rm.get_table("table2_x_merged").parent_table_name == "table1_x"
