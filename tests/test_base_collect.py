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
    Collected,
    CollectArgs,
    CollectCtx,
    Database,
    DataManager,
    DesignCtx,
    ToolMetadata,
    build_collect_parser,
    collect_from_args,
)

UPDATE = ToolMetadata("alphafold3", "update")
CREATE = ToolMetadata("diffused", "create")


def collect(metadata, collect_fn, add_extra_args_fn=None, args_type=CollectArgs):
    """Parse argv and run, mirroring the former ``collect`` wrapper (now split into
    ``build_collect_parser`` + ``collect_from_args``, composed by the ``sapia`` CLI)."""
    parser = build_collect_parser(metadata, add_extra_args_fn)
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

        def one(d: DesignCtx):
            # status defaults to "OK" -> <leaf>_status; extra columns via data.
            yield Collected(data={"score": 1.5})

        return one

    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", "db0"])
    collect(metadata=UPDATE, collect_fn=collect_fn)

    out = DataManager(tmp_path).read_frame("db0")
    assert out.at["r1", "alphafold3_status"] == "OK"
    assert out.at["r1", "score"] == 1.5


def test_collect_update_ready_skips_already_ok(tmp_path, monkeypatch):
    # An update collect resumes: ctx.ready drops rows already status=="OK", so the
    # collect_fn only iterates pending rows (the former inline skip-guard, now in
    # the framework).
    dm = DataManager(tmp_path)
    df = dm.read_frame("db0")
    df = dm.update(df, "done", {"sequence": "AAA", "alphafold3_status": "OK"})
    df = dm.update(df, "pending", {"sequence": "BBB"})
    dm.write_frame("db0", df)
    _make_out_dir(tmp_path, "db0", UPDATE.name)

    seen = {}

    def collect_fn(ctx: CollectCtx):
        seen["ready"] = list(ctx.ready.index)
        return lambda d: ()  # emit nothing

    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", "db0"])
    collect(metadata=UPDATE, collect_fn=collect_fn)
    assert seen["ready"] == ["pending"]  # "done" was skipped


def test_collect_update_ready_force_reincludes_ok(tmp_path, monkeypatch):
    # --force bypasses the resume filter: every valid row is re-collected.
    dm = DataManager(tmp_path)
    df = dm.read_frame("db0")
    df = dm.update(df, "done", {"sequence": "AAA", "alphafold3_status": "OK"})
    dm.write_frame("db0", df)
    _make_out_dir(tmp_path, "db0", UPDATE.name)

    seen = {}

    def collect_fn(ctx: CollectCtx):
        seen["ready"] = list(ctx.ready.index)
        return lambda d: ()  # emit nothing

    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", "db0", "--force"])
    collect(metadata=UPDATE, collect_fn=collect_fn)
    assert seen["ready"] == ["done"]  # --force re-includes collected rows


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

        def one(d: DesignCtx):
            # A create tool mints a child row and names its parent; the framework
            # stamps parent_db/gen and validates the parent edge.
            yield Collected(name=f"{d.name}_d0", parent=d.name, data={"sequence": "CCC"})

        return one

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
        # no parent -> no parent_name stamped on the row
        return lambda d: [Collected(name=f"{d.name}_d0", data={"sequence": "CCC"})]

    def unknown(ctx: CollectCtx):
        # parent not present in the parent db
        return lambda d: [
            Collected(name=f"{d.name}_d0", parent="ZZZ", data={"sequence": "CCC"})
        ]

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
        # a row keyed to a name not already in the db (name override)
        return lambda d: [Collected(name="rNEW")]

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
        collect(metadata=UPDATE, collect_fn=lambda ctx: (lambda d: []))


def test_by_design_stamps_path_and_status(tmp_path, monkeypatch):
    # A Collected's path/status land in the leaf-keyed <leaf>_path / <leaf>_status
    # columns; data lands as-is.
    dm = DataManager(tmp_path)
    dm.write_frame("db0", dm.update(dm.read_frame("db0"), "r1", {"sequence": "AAA"}))
    _make_out_dir(tmp_path, "db0", UPDATE.name)
    model = tmp_path / "r1_model.cif"

    def collect_fn(ctx: CollectCtx):
        return lambda d: [Collected(path=model, data={"ptm": 0.9})]

    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", "db0"])
    collect(metadata=UPDATE, collect_fn=collect_fn)

    out = DataManager(tmp_path).read_frame("db0")
    assert out.at["r1", "alphafold3_status"] == "OK"
    assert out.at["r1", "alphafold3_path"] == str(model)
    assert out.at["r1", "ptm"] == 0.9


def test_by_design_status_none_suppresses_leaf_status(tmp_path, monkeypatch):
    # status=None: the tool owns all its columns via data (e.g. prefix-keyed
    # comparison columns), and no <leaf>_status column is written.
    dm = DataManager(tmp_path)
    dm.write_frame("db0", dm.update(dm.read_frame("db0"), "r1", {"sequence": "AAA"}))
    _make_out_dir(tmp_path, "db0", UPDATE.name)

    def collect_fn(ctx: CollectCtx):
        return lambda d: [
            Collected(status=None, data={"cmp_status": "OK", "cmp_TM1": 0.87})
        ]

    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", "db0"])
    collect(metadata=UPDATE, collect_fn=collect_fn)

    out = DataManager(tmp_path).read_frame("db0")
    assert "alphafold3_status" not in out.columns  # suppressed
    assert out.at["r1", "cmp_status"] == "OK"
    assert out.at["r1", "cmp_TM1"] == 0.87


def test_by_design_create_mints_multiple_children(tmp_path, monkeypatch):
    # A create tool can yield several child rows per ready parent; each gets its
    # parent_name, and the framework stamps parent_db/gen on all of them.
    child = _reserve_child(tmp_path)

    def collect_fn(ctx: CollectCtx):
        def one(d: DesignCtx):
            for i in range(2):
                yield Collected(
                    name=f"{d.name}_d{i}", parent=d.name, data={"iteration": i}
                )

        return one

    monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "-d", child])
    collect(metadata=CREATE, collect_fn=collect_fn)

    df = DataManager(tmp_path).read_frame(child)
    for i in range(2):
        row = f"S0_d{i}"
        assert df.at[row, PARENT_NAME] == "S0"
        assert df.at[row, PARENT_DB] == "db0_worms"
        assert df.at[row, GEN] == 1
        assert df.at[row, "iteration"] == i
