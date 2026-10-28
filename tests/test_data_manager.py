"""Tests for DataManager: updates + guard, lineage resolution, and the registry."""

import pandas as pd
import pytest

from prosapia.core import (
    GEN,
    PARENT_TABLE,
    PARENT_NAME,
    Table,
    DataManager,
)

# Registry handles registered by the tests below.
TABLE0 = Table(
    table_name="table0_worms",
    gen=0,
    table_label="worms",
    parent_table_name=None,
    tool_name="worms",
)
TABLE1 = Table(
    table_name="table1_worms",
    gen=1,
    table_label="worms",
    parent_table_name="table0_worms",
    tool_name="diffusion",
)

# --- update + sequence uniqueness guard ---------------------------------------


def test_update_adds_columns_and_rows(tmp_path):
    dm = DataManager(tmp_path)
    df = dm.read_frame("table")
    df = dm.update(df, "r1", {"a": 1, "b": "x"})
    assert df.at["r1", "a"] == 1
    assert df.at["r1", "b"] == "x"


# --- lineage resolution -------------------------------------------------------


def _build_chain(tmp_path):
    dm = DataManager(tmp_path)
    dm.rm.register_table(TABLE0)
    df0 = dm.update(
        dm.read_frame("table0_worms"), "S0", {"n_subunits": 11, "sequence": "AAA"}
    )
    dm.write_frame("table0_worms", df0)
    dm.rm.register_table(TABLE1)
    df1 = dm.update(
        dm.read_frame("table1_worms"),
        "S0_d0",
        {PARENT_NAME: "S0", PARENT_TABLE: "table0_worms", "sequence": "BBB"},
    )
    dm.write_frame("table1_worms", df1)
    return dm


def test_trace_lineage(tmp_path):
    dm = _build_chain(tmp_path)
    assert dm.trace_lineage("table1_worms", "S0_d0") == [("table0_worms", "S0")]
    assert dm.trace_lineage("table1_worms", "S0_d0", include_self=True) == [
        ("table1_worms", "S0_d0"),
        ("table0_worms", "S0"),
    ]


def test_lookup_local_inherited_and_missing(tmp_path):
    dm = _build_chain(tmp_path)
    df1 = dm.read_frame("table1_worms")
    assert dm.lookup(df1, "S0_d0", "n_subunits") == 11  # inherited from root
    assert dm.lookup(df1, "S0_d0", "sequence") == "BBB"  # local value wins
    assert pd.isna(dm.lookup(df1, "S0_d0", "nope"))  # absent -> default


def test_lookup_table_qualified(tmp_path):
    dm = _build_chain(tmp_path)
    df1 = dm.read_frame("table1_worms")
    # the older copy of a repeated column
    assert dm.lookup(df1, "S0_d0", "table0_worms.sequence") == "AAA"
    # df's own table, named via ``table``
    assert (
        dm.lookup(df1, "S0_d0", "table1_worms.sequence", table="table1_worms")
        == "BBB"
    )
    # pinned: no fall-through to the ancestor's value
    assert pd.isna(
        dm.lookup(df1, "S0_d0", "table1_worms.n_subunits", table="table1_worms")
    )
    # an unregistered prefix is a plain column name
    assert pd.isna(dm.lookup(df1, "S0_d0", "table9_x.sequence"))


# --- table catalog (registry) ----------------------------------------------


def test_derive_child_root_inherit_and_fork(tmp_path):
    dm = DataManager(tmp_path)
    root = dm.rm.derive_new_table(None, "worms")
    assert (root.table_name, root.gen, root.table_label) == ("table0_worms", 0, "worms")
    dm.rm.register_table(TABLE0)
    # No label -> inherit the parent's label, bump the generation.
    child = dm.rm.derive_new_table("table0_worms", "")
    assert (child.table_name, child.gen, child.table_label) == (
        "table1_worms",
        1,
        "worms",
    )
    dm.rm.register_table(TABLE1)
    # A label -> append (breadcrumb) onto the parent's label.
    grandchild = dm.rm.derive_new_table("table1_worms", "hl")
    assert (grandchild.table_name, grandchild.gen, grandchild.table_label) == (
        "table2_worms_hl",
        2,
        "worms_hl",
    )


def test_derive_child_optional_label(tmp_path):
    # Labels are optional: an unlabelled chain stays table0 -> table1 (no trailing _).
    dm = DataManager(tmp_path)
    root = dm.rm.derive_new_table(None, "")
    assert (root.table_name, root.gen, root.table_label) == ("table0", 0, "")
    dm.rm.register_table(
        Table(table_name="table0", gen=0, table_label="", tool_name="worms")
    )
    child = dm.rm.derive_new_table("table0", "")
    assert (child.table_name, child.gen, child.table_label) == ("table1", 1, "")
    # A label on an unlabelled parent starts the breadcrumb cleanly (no leading _).
    forked = dm.rm.derive_new_table("table0", "hl")
    assert (forked.table_name, forked.gen, forked.table_label) == ("table1_hl", 1, "hl")


def test_derive_child_errors(tmp_path):
    dm = DataManager(tmp_path)
    with pytest.raises(KeyError):
        dm.rm.derive_new_table("missing", "x")  # unknown parent


def test_register_table_idempotent_on_match(tmp_path):
    # Registration is idempotent: re-registering the same table (e.g. a resubmit of a
    # failed CREATE job) is a no-op that preserves the original created_at.
    dm = DataManager(tmp_path)
    dm.rm.register_table(TABLE0)
    created_at = dm.rm.get_registry().at["table0_worms", "created_at"]
    dm.rm.register_table(TABLE0)
    assert dm.rm.get_registry().at["table0_worms", "created_at"] == created_at


def test_register_table_raises_on_conflict(tmp_path):
    # Identity is name + parent + gen + label; a differing parent is a real conflict.
    dm = DataManager(tmp_path)
    dm.rm.register_table(TABLE0)
    dm.rm.register_table(TABLE1)
    with pytest.raises(ValueError):
        dm.rm.register_table(
            Table(
                table_name="table1_worms",
                gen=1,
                table_label="worms",
                parent_table_name="table0_worms_other",  # different parent
                tool_name="diffusion",
            )
        )


def test_register_table_tool_not_in_identity(tmp_path):
    # ``tool`` is provenance only, not identity: re-registering the same lineage
    # with a different tool is an idempotent no-op that preserves the original tool.
    dm = DataManager(tmp_path)
    dm.rm.register_table(TABLE0)
    dm.rm.register_table(
        Table(
            table_name="table0_worms",
            gen=0,
            table_label="worms",
            parent_table_name=None,
            tool_name="proteinmpnn",  # different tool, same lineage
        )
    )
    assert dm.rm.get_registry().at["table0_worms", "tool"] == "worms"


def test_get_table_roundtrip(tmp_path):
    # get_table joins registry metadata onto the handle; unregistered names get
    # a bare handle with None metadata.
    dm = DataManager(tmp_path)
    dm.rm.register_table(TABLE1)  # also implies table0 parent edge recorded as-is
    dm.rm.register_table(TABLE0)
    handle = dm.rm.get_table("table1_worms")
    assert handle.gen == 1
    assert handle.table_label == "worms"
    assert handle.parent_table_name == "table0_worms"
    assert handle.tool_name == "diffusion"

    unknown = dm.rm.get_table("nope")
    assert unknown.gen is None
    assert unknown.parent_table_name is None


def test_db_graph(tmp_path):
    dm = DataManager(tmp_path)
    dm.rm.register_table(TABLE0)
    g = dm.rm.get_registry()
    assert "table0_worms" in g.index
    assert g.at["table0_worms", GEN] == 0
    assert g.at["table0_worms", "table_label"] == "worms"
    assert g.at["table0_worms", PARENT_TABLE] == "root"  # root sentinel, not "" / NaN


# --- context manager ----------------------------------------------------------


def test_context_manager_reads_updates_and_persists(tmp_path):
    # Behavioral: the unpacked pieces let you read -> update -> write and reach the
    # registry; we assert the persisted effect, not the unpack's shape/identity.
    with DataManager(tmp_path) as (manager, (read_frame, write_frame), rm):
        df = manager.update(read_frame("table"), "r1", {"a": 1})
        write_frame("table", df)
        rm.register_table(TABLE0)
    # Scope-only exit: data was persisted and re-reads see it.
    assert DataManager(tmp_path).read_frame("table").at["r1", "a"] == 1
    assert "table0_worms" in DataManager(tmp_path).rm.get_registry().index


def test_context_manager_does_not_suppress_exceptions(tmp_path):
    # __exit__ returns False, so an error inside the block propagates.
    with pytest.raises(ValueError, match="boom"):
        with DataManager(tmp_path) as (manager, (read_frame, _write), _rm):
            manager.update(read_frame("table"), "r1", {"sequence": "AAA"})
            raise ValueError("boom")


# --- apply_updates: one-pass write-back of a CollectResult --------------------


def _empty():
    df = pd.DataFrame()
    df.index.name = "name"
    return df


def test_apply_updates_creates_rows_in_dict_order(tmp_path):
    dm = DataManager(tmp_path)
    df = dm.apply_updates(
        _empty(),
        {
            "S1": {"gen": 0, "sequence": "MK", "x": 1.0},
            "S0": {"gen": 0, "sequence": "MKV", "x": 0.0},
        },
    )
    assert list(df.index) == ["S1", "S0"]
    assert list(df.columns) == ["gen", "sequence", "x"]


def test_apply_updates_overwrites_existing_rows_na_included(tmp_path):
    dm = DataManager(tmp_path)
    df = dm.apply_updates(_empty(), {"S0": {"x": 1.0}, "S1": {"x": 2.0}})
    df["boltz_path"] = [float("nan")] * 2  # all-NaN float column, as read from TSV
    df = dm.apply_updates(
        df,
        {
            "S0": {"boltz_path": "/r/0.cif", "boltz_status": "OK"},
            "S1": {"boltz_path": pd.NA, "boltz_status": "failed"},
        },
    )
    assert df.at["S0", "boltz_path"] == "/r/0.cif"  # str into a float column widens
    assert pd.isna(df.at["S1", "boltz_path"])
    assert df.at["S1", "x"] == 2.0  # untouched column preserved
    # A re-collect that reports no path must overwrite the old one (disk wins).
    df = dm.apply_updates(df, {"S0": {"boltz_path": pd.NA, "boltz_status": "failed"}})
    assert pd.isna(df.at["S0", "boltz_path"])


def test_apply_updates_mixes_existing_and_new_rows(tmp_path):
    dm = DataManager(tmp_path)
    df = dm.apply_updates(_empty(), {"S0": {"x": 1.0}})
    df = dm.apply_updates(df, {"S0": {"x": 9.0}, "S9": {"x": 1.0, "gen": 0}})
    assert df.at["S0", "x"] == 9.0
    assert list(df.index) == ["S0", "S9"]
    assert pd.isna(df.at["S0", "gen"])


def test_apply_updates_partial_row_touches_only_its_columns(tmp_path):
    dm = DataManager(tmp_path)
    df = dm.apply_updates(_empty(), {"S0": {"x": 1.0, "boltz_status": "OK"}})
    df = dm.apply_updates(df, {"S0": {"boltz_status": "missing"}})
    assert df.at["S0", "boltz_status"] == "missing"
    assert df.at["S0", "x"] == 1.0


def test_apply_updates_overwrites_a_sequence_like_any_column(tmp_path):
    # The data layer knows nothing about tools: a rewritten sequence is just a
    # rewritten cell. Re-creating a design is a delete + run, never a --force.
    dm = DataManager(tmp_path)
    df = dm.apply_updates(_empty(), {"S0": {"sequence": "MKV"}})
    df = dm.apply_updates(df, {"S0": {"sequence": "DIFFERENT"}})
    assert df.at["S0", "sequence"] == "DIFFERENT"


def test_apply_updates_empty_is_noop(tmp_path):
    dm = DataManager(tmp_path)
    df = dm.apply_updates(_empty(), {"S0": {"x": 1.0}})
    assert dm.apply_updates(df, {}) is df


def test_apply_updates_does_not_fragment(tmp_path):
    import warnings

    dm = DataManager(tmp_path)
    rows = {f"D{i}": {"a": i, "b": "ok", "c": f"/r/{i}", "d": 1.5} for i in range(5000)}
    with warnings.catch_warnings():
        warnings.simplefilter("error", pd.errors.PerformanceWarning)
        df = dm.apply_updates(_empty(), rows)
        df = dm.apply_updates(df, {k: {"b": "failed"} for k in rows})
    assert len(df) == 5000 and (df["b"] == "failed").all()
