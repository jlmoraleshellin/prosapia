"""Tests for the tool-level verbs: ``run_tool`` collects earlier submissions before
it submits, ``collect_tool`` is the plain collect."""

from argparse import Namespace
from pathlib import Path

import pytest

from prosapia.core import tool as tool_mod
from prosapia.core.data_manager import DataManager, Table
from prosapia.core.naming import SUBMISSIONS_DIRNAME
from prosapia.core.tool import Tool, collect_tool, run_tool


def _tool(action):
    return Tool(
        name="mytool",
        action=action,
        default_script="mytool.sh",
        default_input_column="pdb",
        build_manifest_fn=lambda ctx: [],
        collect_fn=lambda ctx: lambda d: (),
    )


def _run_args(run_dir, table, force=False, table_label=""):
    return Namespace(
        run_dir=run_dir, table=table, dir_label="", force=force, table_label=table_label
    )


@pytest.fixture
def calls(monkeypatch):
    """Record the driver calls instead of submitting or collecting."""
    seen = []
    monkeypatch.setattr(
        tool_mod,
        "collect_from_args",
        lambda meta, fn, args: seen.append(("collect", meta.name, args)),
    )
    monkeypatch.setattr(
        tool_mod,
        "run_from_args",
        lambda meta, fn, args: seen.append(("run", meta.name, args)),
    )
    return seen


def _register(run_dir: Path, *tables: Table):
    dm = DataManager(run_dir)
    for t in tables:
        dm.rm.register_table(t)


def test_first_run_does_not_collect(tmp_path, calls):
    _register(tmp_path, Table("table0", 0, "", None, "seed"))
    run_tool(_tool("update"), _run_args(tmp_path, "table0"))
    assert [c[0] for c in calls] == ["run"]


def test_resubmit_collects_then_runs(tmp_path, calls):
    _register(tmp_path, Table("table0", 0, "", None, "seed"))
    (tmp_path / "table0" / "mytool" / SUBMISSIONS_DIRNAME / "00").mkdir(parents=True)
    run_tool(_tool("update"), _run_args(tmp_path, "table0", force=True))
    assert [c[0] for c in calls] == ["collect", "run"]
    collect_args, run_args = calls[0][2], calls[1][2]
    assert collect_args.table == "table0"
    assert collect_args.force is False  # run's --force never makes collect re-read
    assert run_args.force is True


def test_create_tool_collects_the_child_table(tmp_path, calls):
    _register(tmp_path, Table("table0", 0, "", None, "seed"))
    (tmp_path / "table1_x" / "mytool" / SUBMISSIONS_DIRNAME / "00").mkdir(parents=True)
    run_tool(_tool("create"), _run_args(tmp_path, "table0", table_label="x"))
    assert [c[0] for c in calls] == ["collect", "run"]
    assert calls[0][2].table == "table1_x"
    assert calls[1][2].table == "table0"  # the run still iterates the parent


def test_root_run_never_collects(tmp_path, calls):
    (tmp_path / "table0" / "mytool" / SUBMISSIONS_DIRNAME / "00").mkdir(parents=True)
    run_tool(_tool("create"), _run_args(tmp_path, None))
    assert [c[0] for c in calls] == ["run"]


def test_collect_failure_aborts_the_submit(tmp_path, calls, monkeypatch):
    _register(tmp_path, Table("table0", 0, "", None, "seed"))
    (tmp_path / "table0" / "mytool" / SUBMISSIONS_DIRNAME / "00").mkdir(parents=True)

    def boom(meta, fn, args):
        raise RuntimeError("collect broke")

    monkeypatch.setattr(tool_mod, "collect_from_args", boom)
    with pytest.raises(RuntimeError, match="collect broke"):
        run_tool(_tool("update"), _run_args(tmp_path, "table0"))
    assert calls == []


def test_collect_tool_is_the_plain_collect(tmp_path, calls):
    args = Namespace(run_dir=tmp_path, table="table0", dir_label="", force=False)
    collect_tool(_tool("update"), args)
    assert [c[0] for c in calls] == ["collect"]
    assert calls[0][2] is args
