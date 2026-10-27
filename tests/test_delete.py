"""Tests for ``sapia delete``: removing a leaf's dir and columns, or its table."""

import json

import pytest

from prosapia.cli.delete import DeleteArgs, delete_from_args, describe, plan_delete
from prosapia.core import GEN, PARENT_NAME, PARENT_TABLE, DataManager, Table
from prosapia.core.data_manager import REGISTRY_TABLE
from prosapia.core.naming import RUN_META_FILENAME, SUBMISSIONS_DIRNAME


def _write(dm: DataManager, table: Table, rows: dict[str, dict]) -> None:
    dm.rm.register_table(table)
    df = dm.read_frame(table.table_name)
    for name, data in rows.items():
        df = dm.update(df, name, data)
    dm.write_frame(table.table_name, df)


def _leaf(run_dir, table: str, leaf: str, tool: str | None) -> None:
    d = run_dir / table / leaf
    (d / SUBMISSIONS_DIRNAME / "00").mkdir(parents=True)
    (d / f"{leaf}_logs").mkdir()
    (d / SUBMISSIONS_DIRNAME / "00" / "out.pdb").write_text("x")
    if tool is not None:
        (d / RUN_META_FILENAME).write_text(json.dumps({"tool": tool}))


def _cols(leaf: str) -> dict:
    return {
        f"{leaf}_status": "OK",
        f"{leaf}_path": f"{leaf}/out.pdb",
        f"{leaf}_plddt": 0.9,
    }


def _run_dir(tmp_path):
    """root table0 (rfd) -> table1 (mpnn), with update leaves af3 and af3_seed2 on table1."""
    dm = DataManager(tmp_path)
    _write(dm, Table("table0", 0, "", None, "rfd"), {"S0": _cols("rfd")})
    _leaf(tmp_path, "table0", "rfd", "rfd")
    child = {PARENT_NAME: "S0", PARENT_TABLE: "table0", GEN: 1, **_cols("mpnn")}
    _write(
        dm,
        Table("table1", 1, "", "table0", "mpnn"),
        {"S0_0": {**child, **_cols("af3"), **_cols("af3_seed2")}},
    )
    _leaf(tmp_path, "table1", "mpnn", "mpnn")
    _leaf(tmp_path, "table1", "af3", "af3")
    _leaf(tmp_path, "table1", "af3_seed2", "af3")
    return dm


def _delete(tmp_path, table, leaf, recursive=False, dry_run=False):
    delete_from_args(
        DeleteArgs(
            run_dir=tmp_path,
            table=table,
            leaf=leaf,
            recursive=recursive,
            dry_run=dry_run,
        )
    )


def test_update_leaf_drops_its_columns_and_dir_only(tmp_path):
    dm = _run_dir(tmp_path)
    _delete(tmp_path, "table1", "af3")
    df = dm.read_frame("table1")
    assert not [
        c for c in df.columns if c.startswith("af3_") and not c.startswith("af3_seed2_")
    ]
    assert {
        "af3_seed2_status",
        "af3_seed2_path",
        "af3_seed2_plddt",
        "mpnn_status",
    } <= set(df.columns)
    assert not (tmp_path / "table1" / "af3").exists()
    assert (tmp_path / "table1" / "af3_seed2" / SUBMISSIONS_DIRNAME / "00").is_dir()
    assert dm.rm.get_table("table1").gen == 1


def test_update_leaf_with_longer_name_than_sibling(tmp_path):
    dm = _run_dir(tmp_path)
    _delete(tmp_path, "table1", "af3_seed2")
    df = dm.read_frame("table1")
    assert not [c for c in df.columns if c.startswith("af3_seed2_")]
    assert {"af3_status", "af3_path", "af3_plddt"} <= set(df.columns)
    assert (tmp_path / "table1" / "af3").is_dir()


def test_dry_run_touches_nothing(tmp_path, capsys):
    dm = _run_dir(tmp_path)
    before = dm.read_frame("table1")
    _delete(tmp_path, "table1", "af3", dry_run=True)
    out = capsys.readouterr().out
    assert "would remove table1/af3/" in out
    assert "would drop 3 column(s) from table1: af3_status, af3_path, af3_plddt" in out
    assert dm.read_frame("table1").equals(before)
    assert (tmp_path / "table1" / "af3").is_dir()


def test_create_leaf_deletes_its_table(tmp_path):
    dm = _run_dir(tmp_path)
    _delete(tmp_path, "table1", "mpnn")
    assert not (tmp_path / "table1.tsv").exists()
    assert not (tmp_path / "table1").exists()
    assert "table1" not in dm.rm.get_registry().index
    assert dm.rm.get_table("table0").tool_name == "rfd"
    assert (tmp_path / "table0" / "rfd").is_dir()
    assert list(dm.read_frame("table0").index) == ["S0"]


def test_create_leaf_with_descendants_is_refused(tmp_path):
    dm = _run_dir(tmp_path)
    with pytest.raises(SystemExit, match="table1.*--recursive"):
        _delete(tmp_path, "table0", "rfd")
    assert (tmp_path / "table0.tsv").exists()
    assert "table0" in dm.rm.get_registry().index


def test_recursive_deletes_the_subtree(tmp_path):
    dm = _run_dir(tmp_path)
    _delete(tmp_path, "table0", "rfd", recursive=True)
    for t in ("table0", "table1"):
        assert not (tmp_path / f"{t}.tsv").exists()
        assert not (tmp_path / t).exists()
    assert dm.read_frame(REGISTRY_TABLE).empty


def test_merge_leaf_is_a_table(tmp_path):
    dm = _run_dir(tmp_path)
    _write(
        dm,
        Table("table1_merged", 1, "merged", "table0", "merge"),
        {"S0_0_a": _cols("mpnn")},
    )
    _leaf(tmp_path, "table1_merged", "merge", "merge")
    _delete(tmp_path, "table1_merged", "merge")
    assert not (tmp_path / "table1_merged.tsv").exists()
    assert "table1_merged" not in dm.rm.get_registry().index
    assert (tmp_path / "table1.tsv").exists()


def test_create_leaf_without_sidecar_is_recognised_by_name(tmp_path):
    dm = _run_dir(tmp_path)
    (tmp_path / "table1" / "mpnn" / RUN_META_FILENAME).unlink()
    plan = plan_delete(tmp_path, dm.rm, "table1", "mpnn")
    assert plan.tables == ["table1"]
    assert plan.columns == {}


def test_update_leaf_without_sidecar_keeps_the_table(tmp_path):
    dm = _run_dir(tmp_path)
    (tmp_path / "table1" / "af3" / RUN_META_FILENAME).unlink()
    plan = plan_delete(tmp_path, dm.rm, "table1", "af3")
    assert plan.tables == []
    assert plan.columns == {"table1": ["af3_status", "af3_path", "af3_plddt"]}
    assert describe(plan, tmp_path)[0] == "remove table1/af3/"


def test_unknown_leaf_is_refused(tmp_path):
    _run_dir(tmp_path)
    with pytest.raises(SystemExit, match="No leaf"):
        _delete(tmp_path, "table1", "nope")
