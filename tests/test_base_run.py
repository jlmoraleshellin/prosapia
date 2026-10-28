"""Tests for the run driver: row selection (``--where``) and the resume skip
(``ManifestCtx.ready``)."""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from prosapia.core.base_run import (
    ManifestCtx,
    apply_where,
    build_run_parser,
    check_input_column,
    read_run_meta,
    run_from_args,
    write_run_meta,
)
from prosapia.core.naming import PARENT_NAME
from prosapia.core.tool import ToolMetadata


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


# --- ManifestCtx.ready: resume skip for update and create tools ---------------


def _ctx(df, target_df, out_dir, force=False, creates_table=None):
    args = SimpleNamespace(input_column="pdb", force=force)
    if creates_table is None:
        creates_table = target_df is not df
    return ManifestCtx(
        source_df=df,
        target_df=target_df,
        args=args,
        submission_dir=out_dir,
        leaf=out_dir.name,
        tool_creates_table=creates_table,
        lookup=lambda *a, **k: None,
        write_meta=lambda **k: None,
    )


def _parents():
    return pd.DataFrame(
        {"pdb": ["/p1.pdb", "/p2.pdb", "/p3.pdb", None]},
        index=pd.Index(["p1", "p2", "p3", "p4"], name="name"),
    )


def test_ready_update_skips_ok_rows(tmp_path):
    df = _parents()
    df["boltz_status"] = ["OK", "failed", None, None]
    ctx = _ctx(df, df, tmp_path / "table1" / "boltz")
    assert list(ctx.ready.index) == ["p2", "p3"]


def test_ready_create_skips_parents_with_an_ok_child(tmp_path):
    children = pd.DataFrame(
        {
            PARENT_NAME: ["p1", "p1", "p2"],
            "rfdiffusion_status": ["OK", "failed", "failed"],
        },
        index=pd.Index(["p1_d0", "p1_d1", "p2_d0"], name="name"),
    )
    ctx = _ctx(_parents(), children, tmp_path / "table1" / "rfdiffusion")
    # p1 has an OK child -> done; p2 only failed children -> resubmit;
    # p3 never produced a child -> resubmit; p4 has no input -> never ready.
    assert list(ctx.ready.index) == ["p2", "p3"]


def test_ready_create_submits_everything_before_first_collect(tmp_path):
    empty = pd.DataFrame()
    empty.index.name = "name"
    ctx = _ctx(_parents(), empty, tmp_path / "table1" / "rfdiffusion")
    assert list(ctx.ready.index) == ["p1", "p2", "p3"]


def test_ready_create_ignores_other_leafs_status(tmp_path):
    children = pd.DataFrame(
        {PARENT_NAME: ["p1"], "rfdiffusion_other_status": ["OK"]},
        index=pd.Index(["p1_d0"], name="name"),
    )
    ctx = _ctx(_parents(), children, tmp_path / "table1" / "rfdiffusion")
    assert list(ctx.ready.index) == ["p1", "p2", "p3"]


def test_ready_create_ignores_source_rows_it_produced(tmp_path):
    # A proteinmpnn child table carries proteinmpnn_status == OK on every row it
    # minted. Running proteinmpnn again on that table must not read that as done.
    df = _parents()
    df["proteinmpnn_status"] = ["OK", "OK", "OK", "OK"]
    empty = pd.DataFrame()
    empty.index.name = "name"
    ctx = _ctx(df, empty, tmp_path / "table2" / "proteinmpnn", creates_table=True)
    assert list(ctx.ready.index) == ["p1", "p2", "p3"]


def test_ready_force_reincludes_done_parents(tmp_path):
    children = pd.DataFrame(
        {PARENT_NAME: ["p1"], "rfdiffusion_status": ["OK"]},
        index=pd.Index(["p1_d0"], name="name"),
    )
    ctx = _ctx(_parents(), children, tmp_path / "table1" / "rfdiffusion", force=True)
    assert list(ctx.ready.index) == ["p1", "p2", "p3"]


# --- check_input_column: one leaf, one input column ---------------------------


def test_check_input_column_passes_without_sidecar(tmp_path):
    check_input_column(tmp_path, "pdb")


def test_check_input_column_passes_on_same_column(tmp_path):
    write_run_meta(tmp_path, input_column="pdb")
    check_input_column(tmp_path, "pdb")


def test_check_input_column_refuses_a_different_column(tmp_path):
    leaf = tmp_path / "boltz"
    leaf.mkdir()
    write_run_meta(leaf, input_column="pdb")
    with pytest.raises(SystemExit, match="'boltz'.*'pdb'.*'relaxed_pdb'.*--dir-label"):
        check_input_column(leaf, "relaxed_pdb")


# --- the run sidecar records the tool's own flags ----------------------------


def _add_tool_flags(parser):
    parser.add_argument("--alpha", type=int, default=1)
    parser.add_argument("--pdb-in", type=Path, default=None)


def test_run_parser_records_the_tool_flags():
    parser = build_run_parser(
        ToolMetadata("t", "update"), "t.sh", "pdb", _add_tool_flags
    )
    assert parser.parse_args(["run", "-t", "t0"]).tool_args == ["alpha", "pdb_in"]
    bare = build_run_parser(ToolMetadata("t", "update"), "t.sh", "pdb")
    assert bare.parse_args(["run", "-t", "t0"]).tool_args == []


def test_run_meta_serializes_paths(tmp_path):
    write_run_meta(tmp_path, args={"pdb_in": Path("in/x.pdb")})
    assert read_run_meta(tmp_path)["args"] == {"pdb_in": "in/x.pdb"}


def test_run_writes_tool_flags_to_the_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "prosapia.core.base_run.get_executor", lambda name: lambda ctx: None
    )
    metadata = ToolMetadata("t", "update")
    parser = build_run_parser(metadata, "t.sh", "pdb", _add_tool_flags)
    args = parser.parse_args(
        [str(tmp_path), "-t", "t0", "--alpha", "3", "--pdb-in", "x.pdb"]
    )
    run_from_args(metadata, lambda ctx: [("row",)], args)
    meta = read_run_meta(tmp_path / "t0" / "t")
    assert meta["args"] == {"alpha": 3, "pdb_in": "x.pdb"}
    assert meta["input_column"] == "pdb"
