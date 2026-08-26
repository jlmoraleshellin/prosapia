"""Tests for DataManager: updates + guard, lineage resolution, and the registry."""

import pandas as pd
import pytest

from prosapia.core import (
    GEN,
    PARENT_DB,
    PARENT_NAME,
    Database,
    DataManager,
)

# Registry handles registered by the tests below.
DATABASE0 = Database(
    db_name="db0_worms",
    gen=0,
    db_label="worms",
    parent_db_name=None,
    tool_name="worms",
)
DATABASE1 = Database(
    db_name="db1_worms",
    gen=1,
    db_label="worms",
    parent_db_name="db0_worms",
    tool_name="diffusion",
)

# --- update + sequence uniqueness guard ---------------------------------------


def test_update_adds_columns_and_rows(tmp_path):
    dm = DataManager(tmp_path)
    df = dm.read_frame("db")
    df = dm.update(df, "r1", {"a": 1, "b": "x"})
    assert df.at["r1", "a"] == 1
    assert df.at["r1", "b"] == "x"


def test_sequence_collision_guard(tmp_path):
    dm = DataManager(tmp_path)
    df = dm.read_frame("db")
    df = dm.update(df, "r1", {"sequence": "AAA"})
    with pytest.raises(ValueError):
        dm.update(df, "r1", {"sequence": "BBB"})  # different sequence, same name
    # Re-stating the same sequence (or non-sequence updates) is allowed.
    df = dm.update(df, "r1", {"sequence": "AAA", "score": 1.0})
    assert df.at["r1", "score"] == 1.0


# --- lineage resolution -------------------------------------------------------


def _build_chain(tmp_path):
    dm = DataManager(tmp_path)
    dm.rm.register_database(DATABASE0)
    df0 = dm.update(
        dm.read_frame("db0_worms"), "S0", {"n_subunits": 11, "sequence": "AAA"}
    )
    dm.write_frame("db0_worms", df0)
    dm.rm.register_database(DATABASE1)
    df1 = dm.update(
        dm.read_frame("db1_worms"),
        "S0_d0",
        {PARENT_NAME: "S0", PARENT_DB: "db0_worms", "sequence": "BBB"},
    )
    dm.write_frame("db1_worms", df1)
    return dm


def test_trace_lineage(tmp_path):
    dm = _build_chain(tmp_path)
    assert dm.trace_lineage("db1_worms", "S0_d0") == [("db0_worms", "S0")]
    assert dm.trace_lineage("db1_worms", "S0_d0", include_self=True) == [
        ("db1_worms", "S0_d0"),
        ("db0_worms", "S0"),
    ]


def test_lookup_local_inherited_and_missing(tmp_path):
    dm = _build_chain(tmp_path)
    df1 = dm.read_frame("db1_worms")
    assert dm.lookup(df1, "S0_d0", "n_subunits") == 11  # inherited from root
    assert dm.lookup(df1, "S0_d0", "sequence") == "BBB"  # local value wins
    assert pd.isna(dm.lookup(df1, "S0_d0", "nope"))  # absent -> default


# --- database catalog (registry) ----------------------------------------------


def test_derive_child_root_inherit_and_fork(tmp_path):
    dm = DataManager(tmp_path)
    root = dm.rm.derive_new_db(None, "worms")
    assert (root.db_name, root.gen, root.db_label) == ("db0_worms", 0, "worms")
    dm.rm.register_database(DATABASE0)
    # No label -> inherit the parent's label, bump the generation.
    child = dm.rm.derive_new_db("db0_worms", "")
    assert (child.db_name, child.gen, child.db_label) == ("db1_worms", 1, "worms")
    dm.rm.register_database(DATABASE1)
    # A label -> append (breadcrumb) onto the parent's label.
    grandchild = dm.rm.derive_new_db("db1_worms", "hl")
    assert (grandchild.db_name, grandchild.gen, grandchild.db_label) == (
        "db2_worms_hl",
        2,
        "worms_hl",
    )


def test_derive_child_optional_label(tmp_path):
    # Labels are optional: an unlabelled chain stays db0 -> db1 (no trailing _).
    dm = DataManager(tmp_path)
    root = dm.rm.derive_new_db(None, "")
    assert (root.db_name, root.gen, root.db_label) == ("db0", 0, "")
    dm.rm.register_database(
        Database(db_name="db0", gen=0, db_label="", tool_name="worms")
    )
    child = dm.rm.derive_new_db("db0", "")
    assert (child.db_name, child.gen, child.db_label) == ("db1", 1, "")
    # A label on an unlabelled parent starts the breadcrumb cleanly (no leading _).
    forked = dm.rm.derive_new_db("db0", "hl")
    assert (forked.db_name, forked.gen, forked.db_label) == ("db1_hl", 1, "hl")


def test_derive_child_errors(tmp_path):
    dm = DataManager(tmp_path)
    with pytest.raises(KeyError):
        dm.rm.derive_new_db("missing", "x")  # unknown parent


def test_register_database_idempotent_on_match(tmp_path):
    # Registration is idempotent: re-registering the same db (e.g. a resubmit of a
    # failed CREATE job) is a no-op that preserves the original created_at.
    dm = DataManager(tmp_path)
    dm.rm.register_database(DATABASE0)
    created_at = dm.rm.get_registry().at["db0_worms", "created_at"]
    dm.rm.register_database(DATABASE0)
    assert dm.rm.get_registry().at["db0_worms", "created_at"] == created_at


def test_register_database_raises_on_conflict(tmp_path):
    # Identity is name + parent + gen + label; a differing parent is a real conflict.
    dm = DataManager(tmp_path)
    dm.rm.register_database(DATABASE0)
    dm.rm.register_database(DATABASE1)
    with pytest.raises(ValueError):
        dm.rm.register_database(
            Database(
                db_name="db1_worms",
                gen=1,
                db_label="worms",
                parent_db_name="db0_worms_other",  # different parent
                tool_name="diffusion",
            )
        )


def test_register_database_tool_not_in_identity(tmp_path):
    # ``tool`` is provenance only, not identity: re-registering the same lineage
    # with a different tool is an idempotent no-op that preserves the original tool.
    dm = DataManager(tmp_path)
    dm.rm.register_database(DATABASE0)
    dm.rm.register_database(
        Database(
            db_name="db0_worms",
            gen=0,
            db_label="worms",
            parent_db_name=None,
            tool_name="proteinmpnn",  # different tool, same lineage
        )
    )
    assert dm.rm.get_registry().at["db0_worms", "tool"] == "worms"


def test_get_database_roundtrip(tmp_path):
    # get_database joins registry metadata onto the handle; unregistered names get
    # a bare handle with None metadata.
    dm = DataManager(tmp_path)
    dm.rm.register_database(DATABASE1)  # also implies db0 parent edge recorded as-is
    dm.rm.register_database(DATABASE0)
    handle = dm.rm.get_database("db1_worms")
    assert handle.gen == 1
    assert handle.db_label == "worms"
    assert handle.parent_db_name == "db0_worms"
    assert handle.tool_name == "diffusion"

    unknown = dm.rm.get_database("nope")
    assert unknown.gen is None
    assert unknown.parent_db_name is None


def test_db_graph(tmp_path):
    dm = DataManager(tmp_path)
    dm.rm.register_database(DATABASE0)
    g = dm.rm.get_registry()
    assert "db0_worms" in g.index
    assert g.at["db0_worms", GEN] == 0
    assert g.at["db0_worms", "db_label"] == "worms"
    assert g.at["db0_worms", PARENT_DB] == "root"  # root sentinel, not "" / NaN


# --- context manager ----------------------------------------------------------


def test_context_manager_reads_updates_and_persists(tmp_path):
    # Behavioral: the unpacked pieces let you read -> update -> write and reach the
    # registry; we assert the persisted effect, not the unpack's shape/identity.
    with DataManager(tmp_path) as (manager, (read_frame, write_frame), rm):
        df = manager.update(read_frame("db"), "r1", {"a": 1})
        write_frame("db", df)
        rm.register_database(DATABASE0)
    # Scope-only exit: data was persisted and re-reads see it.
    assert DataManager(tmp_path).read_frame("db").at["r1", "a"] == 1
    assert "db0_worms" in DataManager(tmp_path).rm.get_registry().index


def test_context_manager_does_not_suppress_exceptions(tmp_path):
    # __exit__ returns False, so an error inside the block propagates.
    with pytest.raises(ValueError):
        with DataManager(tmp_path) as (manager, (read_frame, _write), _rm):
            df = manager.update(read_frame("db"), "r1", {"sequence": "AAA"})
            manager.update(df, "r1", {"sequence": "BBB"})  # collision -> raises
