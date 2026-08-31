"""End-to-end tests for the unified collect entry-point (``collect``).

Database *creation* is owned by the run script; these tests simulate that by
registering the db (and laying down its output dir) before calling ``collect``,
which only fills an already-existing db. The ``Tool.action`` decides whether the
create contract (resolvable ``PARENT_NAME`` per row) is enforced.
"""

import sys

import pytest

from prosapia.core import (
    GEN,
    PARENT_DB,
    PARENT_NAME,
    CollectArgs,
    CollectCtx,
    Database,
    DataManager,
    ToolMetadata,
    build_collect_parser,
    collect_from_args,
)

UPDATE = ToolMetadata("alphafold3", "update")
CREATE = ToolMetadata("diffused", "create")


def collect(metadata, collect_fn, add_extra_args_fn=None, args_type=CollectArgs):
    """Parse argv and run, mirroring the former ``collect`` wrapper (now split into
    ``build_collect_parser`` + ``collect_from_args``, composed by the ``sapia`` CLI)."""
    parser = build_collect_parser(metadata, "sequence", add_extra_args_fn)
    args = parser.parse_args(namespace=args_type())
    collect_from_args(metadata, collect_fn, args)


def _make_out_dir(run_dir, db_name, tool_leaf):
    """Create the nested tool output dir the run script would have made."""
    out = run_dir / db_name / tool_leaf
    out.mkdir(parents=True)
    return out


def test_collect_update_in_place(tmp_path, monkeypatch):
    # An existing db with a row; its output dir already exists (run made it).
    dm = DataManager(tmp_path)
    df = dm.update(dm.read_frame("db0"), "r1", {"sequence": "AAA"})
    dm.write_frame("db0", df)
    _make_out_dir(tmp_path, "db0", UPDATE.name)

    def collect_fn(ctx: CollectCtx):
        assert ctx.parent_db is None  # not registered -> no parent edge
        assert ctx.parent_df.empty
        return {
            name: {"alphafold3_status": "OK", "score": 1.5} for name in ctx.df.index
        }

    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", "db0"])
    collect(metadata=UPDATE, collect_fn=collect_fn)

    out = DataManager(tmp_path).read_frame("db0")
    assert out.at["r1", "alphafold3_status"] == "OK"
    assert out.at["r1", "score"] == 1.5


def _reserve_child(tmp_path):
    """Register a parent + child db and the child's output dir (as run would)."""
    dm = DataManager(tmp_path)
    dm.rm.register_database(
        Database(
            db_name="db0_worms",
            gen=0,
            db_label="worms",
            parent_db_name=None,
            tool_name="worms",
        )
    )
    df = dm.update(
        dm.read_frame("db0_worms"), "S0", {"sequence": "AAA", "n_subunits": 11}
    )
    dm.write_frame("db0_worms", df)
    child = dm.rm.derive_new_db("db0_worms", "hl")
    assert child.db_name == "db1_worms_hl"
    child.tool_name = CREATE.name
    dm.rm.register_database(child)
    _make_out_dir(tmp_path, child.db_name, CREATE.name)
    return child.db_name


def test_collect_create_fills_child_and_stamps_lineage(tmp_path, monkeypatch):
    child = _reserve_child(tmp_path)
    seen = {}

    def collect_fn(ctx: CollectCtx):
        seen["parent_db"] = ctx.parent_db
        seen["has_S0"] = "S0" in ctx.parent_df.index
        seen["out_dir"] = ctx.out_dir
        # per-row parent name is the collect_fn's job; the framework stamps the rest.
        return {"S0_d0": {"sequence": "CCC", PARENT_NAME: "S0"}}

    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", child])
    collect(metadata=CREATE, collect_fn=collect_fn)

    assert seen["parent_db"] == "db0_worms"
    assert seen["has_S0"] is True
    assert seen["out_dir"] == tmp_path / child / CREATE.name

    dm2 = DataManager(tmp_path)
    df = dm2.read_frame(child)
    assert df.at["S0_d0", PARENT_DB] == "db0_worms"  # stamped by the framework
    assert df.at["S0_d0", GEN] == 1  # read from the registry
    assert df.at["S0_d0", PARENT_NAME] == "S0"  # supplied by collect_fn
    assert dm2.lookup(df, "S0_d0", "n_subunits") == 11  # lineage resolves


def test_collect_create_requires_resolvable_parent_name(tmp_path, monkeypatch):
    child = _reserve_child(tmp_path)

    def missing(ctx: CollectCtx):
        return {"S0_d0": {"sequence": "CCC"}}  # no PARENT_NAME

    def unknown(ctx: CollectCtx):
        return {"S0_d0": {"sequence": "CCC", PARENT_NAME: "ZZZ"}}  # not in parent db

    for fn in (missing, unknown):
        monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", child])
        with pytest.raises(ValueError, match="PARENT_NAME"):
            collect(metadata=CREATE, collect_fn=fn)


def test_collect_update_warns_on_new_row(tmp_path, monkeypatch, capsys):
    dm = DataManager(tmp_path)
    df = dm.update(dm.read_frame("db0"), "r1", {"sequence": "AAA"})
    dm.write_frame("db0", df)
    _make_out_dir(tmp_path, "db0", UPDATE.name)

    def collect_fn(ctx: CollectCtx):
        return {"rNEW": {"alphafold3_status": "OK"}}  # not already in the db

    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", "db0"])
    collect(metadata=UPDATE, collect_fn=collect_fn)

    assert "WARNING" in capsys.readouterr().out
    # the row is still written (warn, not fail)
    assert (
        DataManager(tmp_path).read_frame("db0").at["rNEW", "alphafold3_status"] == "OK"
    )


def test_collect_requires_output_dir(tmp_path, monkeypatch):
    # No run happened -> no output dir -> collect refuses (rather than silently
    # writing an empty db).
    DataManager(tmp_path)

    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", "db0"])
    with pytest.raises(FileNotFoundError):
        collect(metadata=UPDATE, collect_fn=lambda ctx: {})
