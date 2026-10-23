"""Tests for the run driver: row selection (``--where``) and the resume skip
(``ManifestCtx.ready``)."""

from types import SimpleNamespace

import pandas as pd
import pytest

from prosapia.core.base_run import (
    ManifestCtx,
    apply_where,
    check_input_column,
    write_run_meta,
)
from prosapia.core.naming import PARENT_NAME


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


def _ctx(df, target_df, out_dir, force=False):
    args = SimpleNamespace(input_column="pdb", force=force)
    return ManifestCtx(
        source_df=df,
        target_df=target_df,
        args=args,
        submission_dir=out_dir,
        leaf=out_dir.name,
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
